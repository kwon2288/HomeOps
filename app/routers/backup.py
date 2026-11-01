"""HomeOps 백업 · 복구."""
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

from .. import VERSION
from ..auth import require_user
from ..config import BackupCfg
from ..core import Confirm, ctx, require_confirm
from ..store import merge_section
from ..backup import service
from ..backup.archive import NAME_RE, BackupError
from ..backup.remote import FtpTarget, WebDavTarget, targets

router = APIRouter(prefix="/api/backup", tags=["backup"], dependencies=[Depends(require_user)])

MAX_UPLOAD = 2 * 1024**3


class RunBody(BaseModel):
    include_hubs: bool | None = None
    upload: bool = True


class RestoreBody(BaseModel):
    source: str  # local | ftp | webdav
    name: str
    password: str = ""
    confirm: bool = False


def _check_name(name: str) -> None:
    if not NAME_RE.match(name):
        raise HTTPException(400, "잘못된 백업 파일 이름")


def _target(request: Request, key: str):
    t = targets(ctx(request).settings.backup).get(key)
    if not t:
        raise HTTPException(404, f"{key.upper()} 저장소가 켜져 있지 않습니다")
    return t


@router.get("")
def status(request: Request) -> dict:
    c = ctx(request)
    b = c.settings.backup
    return {
        "password_set": bool(b.password),
        "last": service.last_result(c),
        "next_run": service.next_run(c),
        "local": service.list_local(c),
        "targets": {"ftp": b.ftp.enabled, "webdav": b.webdav.enabled},
        "hub_backup_count": len(list(c.runtime.backup_dir.glob("*.lzf"))) if c.runtime.backup_dir.exists() else 0,
    }


@router.post("/run")
async def run(request: Request, body: RunBody | None = None) -> dict:
    body = body or RunBody()
    try:
        return await service.run_backup(ctx(request), VERSION, include_hubs=body.include_hubs, upload=body.upload)
    except BackupError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/local/{name}")
def download(name: str, request: Request) -> FileResponse:
    _check_name(name)
    path = service.local_dir(ctx(request)) / name
    if not path.exists():
        raise HTTPException(404, "파일이 없습니다")
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@router.post("/local/{name}/delete")
def delete_local(name: str, request: Request, body: Confirm | None = None) -> dict:
    require_confirm(body)
    _check_name(name)
    c = ctx(request)
    path = service.local_dir(c) / name
    if not path.exists():
        raise HTTPException(404, "파일이 없습니다")
    path.unlink()
    c.db.audit("백업 파일 삭제", name, "성공")
    return {"ok": True}


@router.get("/remote/{key}")
async def remote_list(key: str, request: Request) -> list[dict]:
    try:
        return await _target(request, key).list()
    except BackupError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/test/{key}")
async def test_target(key: str, request: Request, data: Any = Body(None)) -> dict:
    """저장하지 않은 입력값으로 원격 저장소 연결을 시험한다. 백업 설정 전체를 보낸다."""
    if key not in ("ftp", "webdav") or not isinstance(data, dict):
        raise HTTPException(400, "잘못된 요청")
    c = ctx(request)
    merged = merge_section("backup", data, c.settings.backup.model_dump())
    merged.setdefault(key, {})["enabled"] = True
    try:
        cfg = BackupCfg(**merged)
    except ValidationError as exc:
        err = exc.errors()[0]
        raise HTTPException(422, str(err.get("ctx", {}).get("error") or err["msg"]).replace("Value error, ", "")) from exc
    target = FtpTarget(cfg.ftp) if key == "ftp" else WebDavTarget(cfg.webdav)
    try:
        return {"ok": True, "message": await target.test()}
    except BackupError as exc:
        return {"ok": False, "message": str(exc)}


@router.post("/restore")
async def restore(request: Request, body: RestoreBody) -> dict:
    if not body.confirm:
        raise HTTPException(400, "확인(confirm: true)이 필요한 작업입니다")
    _check_name(body.name)
    c = ctx(request)
    try:
        if body.source == "local":
            path = service.local_dir(c) / body.name
            if not path.exists():
                raise HTTPException(404, "파일이 없습니다")
            data = path.read_bytes()
        elif body.source in ("ftp", "webdav"):
            data = await _target(request, body.source).download(body.name)
        else:
            raise HTTPException(400, "알 수 없는 위치")
        password = body.password or c.settings.backup.password
        return await service.restore(request.app, data, password, VERSION, f"{body.source}:{body.name}")
    except BackupError as exc:
        c.db.audit("HomeOps 복구", f"{body.source}:{body.name}", f"실패: {exc}")
        raise HTTPException(400, str(exc)) from exc


@router.post("/restore-upload")
async def restore_upload(request: Request) -> dict:
    """백업 파일을 그대로 본문으로 받는다. 암호는 X-Backup-Password(URL 인코딩) 헤더."""
    if request.headers.get("x-confirm") != "yes":
        raise HTTPException(400, "확인이 필요한 작업입니다")
    size = int(request.headers.get("content-length") or 0)
    if size > MAX_UPLOAD:
        raise HTTPException(413, "파일이 너무 큽니다")
    data = await request.body()
    c = ctx(request)
    password = unquote(request.headers.get("x-backup-password", "")) or c.settings.backup.password
    try:
        return await service.restore(request.app, data, password, VERSION, "업로드한 파일")
    except BackupError as exc:
        c.db.audit("HomeOps 복구", "업로드한 파일", f"실패: {exc}")
        raise HTTPException(400, str(exc)) from exc
