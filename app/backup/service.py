"""백업 실행 · 보관 개수 정리 · 복구 · 매일 자동 백업."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from ..config import app_backup_dir
from ..core import Ctx
from ..db import Database
from ..store import SettingsStore
from . import archive
from .archive import NAME_RE, BackupError
from .remote import targets

log = logging.getLogger("homeops.backup")
_lock = asyncio.Lock()


def local_dir(c: Ctx) -> Path:
    d = app_backup_dir(c.runtime)
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_local(c: Ctx) -> list[dict]:
    out = []
    for p in local_dir(c).glob("homeops-*.hob"):
        if NAME_RE.match(p.name):
            st = p.stat()
            out.append({"name": p.name, "size": st.st_size, "mtime": int(st.st_mtime)})
    return sorted(out, key=lambda e: e["name"], reverse=True)


def _latest_hub_files(c: Ctx) -> list[Path]:
    d = c.runtime.backup_dir
    if not d.exists():
        return []
    latest: dict[str, Path] = {}
    for p in sorted(d.glob("*.lzf")):
        hub_id = p.name.rsplit("-", 2)[0]
        latest[hub_id] = p  # 이름에 날짜가 들어 있어 정렬 순서상 마지막이 최신
    return list(latest.values())


def _prune_local(c: Ctx, keep: int) -> None:
    files = list_local(c)
    # 복구 직전 자동 백업은 따로 세지 않고 함께 정리
    for e in files[keep:]:
        (local_dir(c) / e["name"]).unlink(missing_ok=True)


async def _prune_remote(target, keep: int) -> None:
    files = await target.list()
    for e in files[keep:]:
        await target.delete(e["name"])


def _save_last(c: Ctx, result: dict) -> None:
    c.db.kv_set("backup_last", json.dumps(result, ensure_ascii=False))


def last_result(c: Ctx) -> dict | None:
    raw = c.db.kv_get("backup_last")
    return json.loads(raw) if raw else None


async def run_backup(c: Ctx, version: str, reason: str = "수동", include_hubs: bool | None = None,
                     upload: bool = True, tag: str = "") -> dict[str, Any]:
    cfg = c.settings.backup
    if not cfg.password:
        raise BackupError("백업 암호를 먼저 설정하세요")
    async with _lock:
        include = cfg.include_hub_backups if include_hubs is None else include_hubs
        hub_files = _latest_hub_files(c) if include else []
        data = await asyncio.to_thread(
            archive.create, c.runtime.db_path, c.runtime.secret_key, cfg.password, version, hub_files,
        )
        name = archive.backup_name(tag)
        path = local_dir(c) / name
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        os.replace(tmp, path)

        uploads: dict[str, str] = {}
        if upload:
            for key, target in targets(cfg).items():
                try:
                    await target.upload(name, data)
                    try:
                        await _prune_remote(target, cfg.keep_remote)
                    except BackupError as exc:
                        log.warning("원격 정리 실패 %s: %s", key, exc)
                    uploads[key] = "성공"
                except BackupError as exc:
                    uploads[key] = f"실패: {exc}"
                except Exception as exc:  # noqa: BLE001
                    uploads[key] = f"실패: {exc.__class__.__name__}"
        _prune_local(c, cfg.keep_local)

    ok = all(v == "성공" for v in uploads.values())
    result = {
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "reason": reason, "name": name, "size": len(data), "hub_files": len(hub_files),
        "uploads": uploads, "ok": ok,
    }
    if not tag:  # 복구 직전 자동 백업은 "마지막 백업"으로 치지 않음
        _save_last(c, result)
    detail = ", ".join(f"{k.upper()} {v}" for k, v in uploads.items())
    c.db.audit(f"HomeOps 백업 ({reason})", name, ("성공" if ok else "일부 실패") + (f" · {detail}" if detail else ""))
    return result


def reload_context(app: FastAPI) -> None:
    """복구로 DB·키가 바뀐 뒤 앱이 쓰는 객체를 다시 만든다."""
    c: Ctx = app.state.ctx
    db = Database(c.runtime.db_path)
    store = SettingsStore(db, c.runtime.secret_key)
    c.db, c.store, c.settings = db, store, store.load()
    app.state.homebridge = None


async def restore(app: FastAPI, data: bytes, password: str, version: str, source: str) -> dict[str, Any]:
    c: Ctx = app.state.ctx
    opened = await asyncio.to_thread(archive.open_backup, data, password)

    safety = None
    if c.settings.backup.password:
        try:
            safety = (await run_backup(c, version, reason="복구 전 자동", upload=False, tag="before-restore"))["name"]
        except BackupError:
            safety = None

    # 백업 실행 기록은 복구 대상이 아니므로 그대로 이어 간다
    keep = {k: c.db.kv_get(k) for k in ("backup_last", "backup_sched_day")}

    async with _lock:
        db_path = c.runtime.db_path
        tmp = db_path.with_suffix(".restore")
        tmp.write_bytes(opened.db)
        for suffix in ("-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
        os.replace(tmp, db_path)

        key_path = db_path.parent / "secret.key"
        key_path.write_text(opened.secret_key)
        key_path.chmod(0o600)
        warning = None
        if c.runtime.secret_from_env:
            if c.runtime.secret_key != opened.secret_key:
                warning = ("HOMEOPS_SECRET_KEY 환경 변수가 백업 당시 키와 달라 저장된 토큰을 풀 수 없습니다. "
                           "환경 변수를 지우거나 연결 설정에서 토큰을 다시 입력하세요.")
        else:
            c.runtime.secret_key = opened.secret_key

        hub_dir = c.runtime.backup_dir
        if opened.hub_files:
            hub_dir.mkdir(parents=True, exist_ok=True)
            for name, content in opened.hub_files.items():
                target = hub_dir / name
                if not target.exists():
                    target.write_bytes(content)

        reload_context(app)
        for k, v in keep.items():
            if v is not None:
                app.state.ctx.db.kv_set(k, v)

    c = app.state.ctx
    c.db.audit("HomeOps 복구", source, "성공" + (f" · 복구 전 상태는 {safety}" if safety else ""))
    return {
        "ok": True,
        "created": opened.manifest.get("created"),
        "version": opened.manifest.get("version"),
        "hub_files": len(opened.hub_files),
        "safety_backup": safety,
        "warning": warning,
    }


def next_run(c: Ctx) -> str | None:
    b = c.settings.backup
    if not (b.schedule_enabled and b.password):
        return None
    tz = ZoneInfo(b.timezone)
    now = datetime.now(tz)
    hh, mm = map(int, b.schedule_time.split(":"))
    run = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if run <= now or c.db.kv_get("backup_sched_day") == now.strftime("%Y-%m-%d"):
        run += timedelta(days=1)
    return run.isoformat(timespec="minutes")


async def scheduler(app: FastAPI, version: str) -> None:
    """30초마다 확인해서 정해진 시각에 하루 한 번 백업한다."""
    while True:
        await asyncio.sleep(30)
        try:
            c: Ctx = app.state.ctx
            b = c.settings.backup
            if not (b.schedule_enabled and b.password):
                continue
            now = datetime.now(ZoneInfo(b.timezone))
            today = now.strftime("%Y-%m-%d")
            if now.strftime("%H:%M") == b.schedule_time and c.db.kv_get("backup_sched_day") != today:
                c.db.kv_set("backup_sched_day", today)
                await run_backup(c, version, reason="자동")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("자동 백업 실패")
            try:
                _save_last(app.state.ctx, {
                    "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "reason": "자동", "ok": False, "error": "자동 백업 실패 (로그 확인)", "uploads": {},
                })
            except Exception:  # noqa: BLE001
                pass
