"""인프라: Synology NAS · Proxmox VE · Portainer."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import require_user
from ..connectors.portainer import Portainer
from ..connectors.proxmox import Proxmox
from ..connectors.synology import Synology
from ..core import NOT_CONFIGURED, Confirm, ctx, guarded, require_confirm, run_action

router = APIRouter(prefix="/api/infra", tags=["infra"], dependencies=[Depends(require_user)])


def _pve(request: Request) -> Proxmox:
    cfg = ctx(request).settings.proxmox
    if not cfg:
        raise HTTPException(404, "Proxmox 연결 설정이 없습니다")
    return Proxmox(cfg)


def _ptn(request: Request) -> Portainer:
    cfg = ctx(request).settings.portainer
    if not cfg:
        raise HTTPException(404, "Portainer 연결 설정이 없습니다")
    return Portainer(cfg)


@router.get("")
async def overview(request: Request) -> dict:
    s = ctx(request).settings

    async def nothing():
        return NOT_CONFIGURED

    nas, pve, ptn = await asyncio.gather(
        guarded(Synology(s.synology).status()) if s.synology else nothing(),
        guarded(Proxmox(s.proxmox).status()) if s.proxmox else nothing(),
        guarded(Portainer(s.portainer).status()) if s.portainer else nothing(),
    )
    return {"nas": nas, "proxmox": pve, "portainer": ptn}


@router.post("/nas/reboot")
async def nas_reboot(request: Request, body: Confirm | None = None) -> dict:
    require_confirm(body)
    c = ctx(request)
    if not c.settings.synology:
        raise HTTPException(404, "NAS 연결 설정이 없습니다")
    return await run_action(c, "NAS 재부팅", c.settings.synology.url, Synology(c.settings.synology).reboot())


@router.post("/proxmox/{node}/{kind}/{vmid}/power/{action}")
async def pve_power(node: str, kind: str, vmid: int, action: str, request: Request, body: Confirm | None = None) -> dict:
    if action != "start":
        require_confirm(body)
    return await run_action(ctx(request), f"Proxmox {action}", f"{node}/{kind}/{vmid}",
                            _pve(request).power(node, kind, vmid, action))


@router.post("/proxmox/{node}/{kind}/{vmid}/snapshot")
async def pve_snapshot(node: str, kind: str, vmid: int, request: Request) -> dict:
    return await run_action(ctx(request), "Proxmox 스냅샷", f"{node}/{kind}/{vmid}",
                            _pve(request).snapshot(node, kind, vmid))


@router.post("/proxmox/{node}/{vmid}/backup")
async def pve_backup(node: str, vmid: int, request: Request) -> dict:
    return await run_action(ctx(request), "Proxmox 백업", f"{node}/{vmid}", _pve(request).backup(node, vmid))


@router.post("/portainer/{endpoint}/containers/{cid}/{action}")
async def ptn_container(endpoint: int, cid: str, action: str, request: Request, body: Confirm | None = None) -> dict:
    if action != "start":
        require_confirm(body)
    return await run_action(ctx(request), f"컨테이너 {action}", cid[:12],
                            _ptn(request).container_action(endpoint, cid, action))


@router.get("/portainer/{endpoint}/containers/{cid}/logs")
async def ptn_logs(endpoint: int, cid: str, request: Request, tail: int = 200) -> dict:
    try:
        return {"logs": await _ptn(request).container_logs(endpoint, cid, tail)}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        from ..connectors.base import describe
        raise HTTPException(502, describe(exc)) from exc


@router.post("/portainer/stacks/{stack_id}/{action}")
async def ptn_stack(stack_id: int, action: str, endpoint: int, request: Request, body: Confirm | None = None) -> dict:
    if action != "start":
        require_confirm(body)
    return await run_action(ctx(request), f"스택 {action}", str(stack_id),
                            _ptn(request).stack_action(stack_id, endpoint, action))
