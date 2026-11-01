"""스마트홈 허브: Hubitat · Home Assistant · Homebridge 상태와 관리 작업."""
from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from ..auth import require_user
from ..connectors.homeassistant import HomeAssistant
from ..connectors.homebridge import Homebridge
from ..connectors.hubitat import Hubitat
from ..core import NOT_CONFIGURED, Confirm, ctx, guarded, require_confirm, run_action

router = APIRouter(prefix="/api/hubs", tags=["hubs"], dependencies=[Depends(require_user)])


def _hub(request: Request, hub_id: str) -> Hubitat:
    cfg = ctx(request).settings.hub(hub_id)
    if not cfg:
        raise HTTPException(404, "등록되지 않은 허브입니다")
    return Hubitat(cfg)


async def _hubitat_status(h: Hubitat) -> dict:
    r = await guarded(h.status())
    if r["data"] is not None:
        r["online"] = bool(r["data"]["online"])
        if not r["online"]:
            r["error"] = "응답 없음"
    else:
        r["data"] = {"id": h.cfg.id, "name": h.cfg.name, "url": h.cfg.url, "role": h.cfg.role}
    return r


async def collect(request: Request) -> dict:
    s = ctx(request).settings

    async def nothing():
        return NOT_CONFIGURED

    hubs = await asyncio.gather(*(_hubitat_status(Hubitat(h)) for h in s.hubitat))
    ha, hb = await asyncio.gather(
        guarded(HomeAssistant(s.home_assistant).status()) if s.home_assistant else nothing(),
        guarded(_homebridge(request).status()) if s.homebridge else nothing(),
    )
    return {"hubitat": list(hubs), "home_assistant": ha, "homebridge": hb}


@router.get("")
async def overview(request: Request) -> dict:
    return await collect(request)


@router.post("/hubitat/{hub_id}/reboot")
async def hub_reboot(hub_id: str, request: Request, body: Confirm | None = None) -> dict:
    require_confirm(body)
    return await run_action(ctx(request), "Hubitat 재부팅", hub_id, _hub(request, hub_id).reboot())


@router.post("/hubitat/{hub_id}/backup")
async def hub_backup(hub_id: str, request: Request) -> dict:
    c = ctx(request)
    return await run_action(c, "Hubitat 백업", hub_id,
                            _hub(request, hub_id).backup(c.runtime.backup_dir, c.runtime.backup_keep))


@router.get("/hubitat/backups")
def hub_backups(request: Request) -> list[dict]:
    d = ctx(request).runtime.backup_dir
    if not d.exists():
        return []
    files = sorted(d.glob("*.lzf"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"file": p.name, "size": p.stat().st_size, "mtime": int(p.stat().st_mtime)} for p in files]


@router.get("/hubitat/backups/{name}")
def hub_backup_download(name: str, request: Request) -> FileResponse:
    if not re.match(r"^[\w\-]+\.lzf$", name):
        raise HTTPException(400, "잘못된 파일 이름")
    path = ctx(request).runtime.backup_dir / name
    if not path.exists():
        raise HTTPException(404, "파일이 없습니다")
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@router.post("/home-assistant/restart")
async def ha_restart(request: Request, body: Confirm | None = None) -> dict:
    require_confirm(body)
    c = ctx(request)
    if not c.settings.home_assistant:
        raise HTTPException(404, "Home Assistant 연결 설정이 없습니다")
    return await run_action(c, "HA 재시작", "home-assistant", HomeAssistant(c.settings.home_assistant).restart())


@router.post("/home-assistant/backup")
async def ha_backup(request: Request) -> dict:
    c = ctx(request)
    if not c.settings.home_assistant:
        raise HTTPException(404, "Home Assistant 연결 설정이 없습니다")
    return await run_action(c, "HA 백업", "home-assistant", HomeAssistant(c.settings.home_assistant).backup())


def _homebridge(request: Request) -> Homebridge:
    app = request.app
    if not getattr(app.state, "homebridge", None):
        cfg = ctx(request).settings.homebridge
        if not cfg:
            raise HTTPException(404, "Homebridge 연결 설정이 없습니다")
        app.state.homebridge = Homebridge(cfg)  # 토큰 재사용
    return app.state.homebridge


@router.post("/homebridge/restart")
async def hb_restart(request: Request, body: Confirm | None = None) -> dict:
    require_confirm(body)
    return await run_action(ctx(request), "Homebridge 재시작", "homebridge", _homebridge(request).restart())
