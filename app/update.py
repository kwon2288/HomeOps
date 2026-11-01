"""웹에서 새 버전 확인 · 업데이트.

설치 방식마다 업데이트하는 방법이 다르다.
- lxc    : install.sh 로 설치. 앱(homeops 계정)은 데이터 폴더에 요청 파일만 쓰고,
           root 로 도는 homeops-update.path → homeops-update.service 가 git pull + install.sh 를 실행한다.
- docker : 새 코드를 데이터 볼륨의 code/ 에 받아 두고 프로세스를 끝낸다. 컨테이너가 다시 뜰 때
           entrypoint.sh 가 이미지보다 새 버전이면 code/ 의 코드로 실행한다.
- 그 밖  : 직접 실행 중 (개발 등) — 확인만 하고 업데이트 방법을 안내한다.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import shutil
import tarfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from . import VERSION
from .auth import require_user
from .backup import service as backup_service
from .backup.archive import BackupError
from .core import Confirm, Ctx, ctx, require_confirm

log = logging.getLogger("homeops.update")
router = APIRouter(prefix="/api/update", tags=["update"], dependencies=[Depends(require_user)])

CHECK_TTL = 3600              # 왼쪽 아래 '새 버전' 표시용 자동 확인 간격 (업데이트 화면은 열 때마다 확인)
HELPER_UNIT = Path("/etc/systemd/system/homeops-update.path")
LEGACY_UPDATER = Path("/usr/local/bin/homeops-update")
MAX_TARBALL = 50 * 1024 * 1024


def repo() -> str:
    return os.environ.get("HOMEOPS_REPO", "kwon2288/HomeOps")


def branch() -> str:
    return os.environ.get("HOMEOPS_BRANCH", "main")


def _headers() -> dict[str, str]:
    token = os.environ.get("HOMEOPS_GITHUB_TOKEN")
    return {"Authorization": f"token {token}"} if token else {}


# ---- 버전 · 변경 이력 ----

def vtuple(v: str | None) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))[:4]


def read_version(text: str) -> str | None:
    m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', text, re.M)
    return m.group(1) if m else None


def changelog(readme: str, current: str) -> list[dict[str, Any]]:
    """README 의 '변경 이력'에서 current 보다 새 버전 항목만 꺼낸다."""
    part = readme.split("## 변경 이력", 1)
    if len(part) < 2:
        return []
    body = re.split(r"^## ", part[1], maxsplit=1, flags=re.M)[0]
    out = []
    for block in re.split(r"^### ", body, flags=re.M)[1:]:
        head, _, rest = block.partition("\n")
        m = re.match(r"v?(\d+(?:\.\d+)*)\s*(?:[—-]\s*(.*))?", head.strip())
        if not m or vtuple(m.group(1)) <= vtuple(current):
            continue
        items = []
        for line in rest.splitlines():
            lm = re.match(r"^(\s*)[-*] (.+)", line)
            if lm:
                items.append({"text": lm.group(2).strip(), "sub": len(lm.group(1)) >= 2})
        out.append({"version": m.group(1), "date": (m.group(2) or "").strip(), "items": items})
    return out


# ---- 설치 방식 ----

def mode() -> str:
    m = os.environ.get("HOMEOPS_INSTALL", "").lower()
    return m if m in ("lxc", "docker") else "manual"


def _udir(c: Ctx) -> Path:
    return c.runtime.db_path.parent / "update"


def capability() -> tuple[bool, str]:
    """(웹에서 업데이트 가능, 안 되면 안내 문구)"""
    m = mode()
    if m == "lxc":
        if HELPER_UNIT.exists():
            return True, ""
        return False, "LXC 콘솔에서 homeops-update 를 한 번 실행하세요. 그다음부터는 여기서 업데이트할 수 있습니다."
    if m == "docker":
        return True, ""
    if LEGACY_UPDATER.exists():
        return False, "LXC 콘솔에서 homeops-update 를 한 번 실행하세요. 그다음부터는 여기서 업데이트할 수 있습니다."
    if Path("/.dockerenv").exists():
        return False, "Portainer에서 스택을 한 번 다시 배포(Pull and redeploy)하세요. 그다음부터는 여기서 업데이트할 수 있습니다."
    return False, "직접 실행 중이라 여기서는 업데이트할 수 없습니다. git pull 후 다시 실행하세요."


# ---- 새 버전 확인 ----

def _cached(c: Ctx) -> dict[str, Any]:
    raw = c.db.kv_get("update_check")
    return json.loads(raw) if raw else {}


async def check(c: Ctx, force: bool = False) -> dict[str, Any]:
    cached = _cached(c)
    if not force and cached and time.time() - cached.get("ts", 0) < CHECK_TTL:
        return cached
    result: dict[str, Any] = {"ts": time.time(), "checked_at": datetime.now().astimezone().isoformat(timespec="seconds")}
    try:
        async with httpx.AsyncClient(timeout=10, headers=_headers(), follow_redirects=True) as h:
            # 브랜치 이름으로 받으면 GitHub가 최대 5분 묵은 파일을 줄 수 있어서, 최신 커밋을 먼저 알아내 그 커밋으로 받는다
            ref = branch()
            try:
                r = await h.get(f"https://api.github.com/repos/{repo()}/commits/{branch()}",
                                headers={"Accept": "application/vnd.github.sha"})
                if r.status_code == 200 and re.fullmatch(r"[0-9a-f]{40}", r.text.strip()):
                    ref = r.text.strip()
            except httpx.HTTPError:
                pass  # API 한도 초과 등 — 브랜치 이름으로 받는다
            base = f"https://raw.githubusercontent.com/{repo()}/{ref}"
            ver, readme = await asyncio.gather(h.get(f"{base}/app/__init__.py"), h.get(f"{base}/README.md"))
        if ver.status_code == 404:
            raise RuntimeError(f"저장소를 찾을 수 없습니다 ({repo()} · {branch()}). 비공개라면 HOMEOPS_GITHUB_TOKEN 을 지정하세요")
        ver.raise_for_status()
        latest = read_version(ver.text)
        if not latest:
            raise RuntimeError("저장소에서 버전 정보를 읽지 못했습니다")
        result["latest"] = latest
        result["readme"] = readme.text if readme.status_code == 200 else ""
    except httpx.HTTPError as exc:
        result["error"] = f"GitHub에 연결하지 못했습니다 ({exc.__class__.__name__})"
    except RuntimeError as exc:
        result["error"] = str(exc)
    if result.get("error") and cached.get("latest"):
        # 확인이 실패해도 이전에 알아낸 버전은 보여 준다
        result = {**cached, "error": result["error"], "ts": result["ts"], "checked_at": result["checked_at"]}
    c.db.kv_set("update_check", json.dumps(result))
    return result


# ---- 진행 상황 ----

_docker_job: dict[str, Any] = {}


def _tail(path: Path, n: int = 60) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def job(c: Ctx) -> dict[str, Any] | None:
    if mode() == "docker":
        return dict(_docker_job) if _docker_job else None
    d = _udir(c)
    if (d / "request").exists():
        return {"state": "queued", "log": "", "started": None, "finished": None}
    state = _read(d / "state")
    if not state:
        return None
    return {"state": state, "log": _tail(d / "update.log"),
            "started": _read(d / "started") or None, "finished": _read(d / "finished") or None}


def status(c: Ctx, chk: dict[str, Any]) -> dict[str, Any]:
    ok, hint = capability()
    latest = chk.get("latest")
    return {
        "mode": mode(), "current": VERSION, "latest": latest,
        "available": bool(latest) and vtuple(latest) > vtuple(VERSION),
        "changelog": changelog(chk.get("readme") or "", VERSION) if latest else [],
        "checked_at": chk.get("checked_at"), "error": chk.get("error"),
        "can_update": ok, "hint": hint, "repo": repo(), "branch": branch(),
        "job": job(c),
    }


# ---- Docker: 새 코드 받기 ----

def _extract(data: bytes, dest: Path) -> str:
    """GitHub tarball 을 dest 에 푼다 (맨 위 폴더 하나는 벗긴다). 새 버전 문자열을 돌려준다."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            parts = Path(m.name).parts[1:]
            if not parts:
                continue
            if m.name.startswith("/") or ".." in parts or not (m.isfile() or m.isdir()):
                continue  # 이상한 항목(절대 경로, 링크 등)은 무시
            target = dest.joinpath(*parts)
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(m)
            if src is None:
                continue
            target.write_bytes(src.read())
            target.chmod(0o755 if m.mode & 0o111 else 0o644)
    init = dest / "app" / "__init__.py"
    ver = read_version(init.read_text()) if init.exists() else None
    if not ver or not (dest / "app" / "main.py").exists():
        raise RuntimeError("받은 파일에 HomeOps 코드가 없습니다")
    return ver


def _restart() -> None:
    """컨테이너를 다시 띄우도록 프로세스를 끝낸다 (restart: unless-stopped). 응답이 나간 뒤에."""
    threading.Timer(1.5, os._exit, (75,)).start()


async def _docker_update(c: Ctx) -> None:
    def say(msg: str) -> None:
        _docker_job["log"] = (_docker_job.get("log", "") + f"{datetime.now():%H:%M:%S} {msg}\n")

    data_dir = c.runtime.db_path.parent
    try:
        url = f"https://codeload.github.com/{repo()}/tar.gz/refs/heads/{branch()}"
        say(f"내려받는 중: {repo()} ({branch()})")
        async with httpx.AsyncClient(timeout=120, headers=_headers(), follow_redirects=True) as h:
            r = await h.get(url)
        r.raise_for_status()
        if len(r.content) > MAX_TARBALL:
            raise RuntimeError("받은 파일이 너무 큽니다")
        say(f"받음 ({len(r.content) // 1024} KB) · 푸는 중")
        new = data_dir / "code.new"
        ver = await asyncio.to_thread(_extract, r.content, new)
        if vtuple(ver) <= vtuple(VERSION):
            shutil.rmtree(new, ignore_errors=True)
            raise RuntimeError(f"받은 버전(v{ver})이 지금 버전보다 새롭지 않습니다")
        cur, prev = data_dir / "code", data_dir / "code.prev"
        shutil.rmtree(prev, ignore_errors=True)
        if cur.exists():
            cur.rename(prev)
        new.rename(cur)
        say(f"v{ver} 준비 완료 · 다시 시작합니다")
        c.db.audit("HomeOps 업데이트", f"v{VERSION} → v{ver}", "다시 시작")
        _docker_job["state"] = "restarting"
        _restart()
    except Exception as exc:  # noqa: BLE001
        msg = str(exc) if isinstance(exc, RuntimeError) else f"{exc.__class__.__name__}: {exc}"
        say(f"실패: {msg}")
        _docker_job.update(state="failed", finished=datetime.now().astimezone().isoformat(timespec="seconds"))
        c.db.audit("HomeOps 업데이트", f"v{VERSION}", f"실패: {msg}")


# ---- API ----

@router.get("")
async def get_status(request: Request, refresh: bool = False) -> dict[str, Any]:
    c = ctx(request)
    return status(c, await check(c, force=refresh))


@router.post("/apply")
async def apply(request: Request, tasks: BackgroundTasks, body: Confirm | None = None) -> dict[str, Any]:
    require_confirm(body)
    c = ctx(request)
    ok, hint = capability()
    if not ok:
        raise HTTPException(400, hint)
    cur = job(c)
    if cur and cur["state"] in ("queued", "running", "restarting"):
        raise HTTPException(409, "이미 업데이트 중입니다")
    chk = await check(c, force=True)
    if not chk.get("latest"):
        raise HTTPException(502, chk.get("error") or "새 버전을 확인하지 못했습니다")
    if vtuple(chk["latest"]) <= vtuple(VERSION):
        raise HTTPException(400, "이미 최신 버전입니다")

    # 되돌릴 수 있도록 업데이트 전에 자동 백업 (백업 암호를 정해 둔 경우)
    backup_name = None
    if c.settings.backup.password:
        try:
            backup_name = (await backup_service.run_backup(c, VERSION, reason="업데이트 전 자동", upload=False,
                                                          tag="before-update"))["name"]
        except BackupError as exc:
            raise HTTPException(500, f"업데이트 전 백업에 실패해서 멈췄습니다: {exc}") from exc

    started = datetime.now().astimezone().isoformat(timespec="seconds")
    if mode() == "lxc":
        d = _udir(c)
        d.mkdir(parents=True, exist_ok=True)
        (d / "request").write_text("update\n")
        c.db.audit("HomeOps 업데이트", f"v{VERSION} → v{chk['latest']}", "시작")
    else:
        _docker_job.clear()
        _docker_job.update(state="running", log="", started=started, finished=None)
        tasks.add_task(_docker_update, c)
    return {"ok": True, "latest": chk["latest"], "backup": backup_name,
            "message": f"v{chk['latest']}(으)로 업데이트를 시작했습니다"}
