"""스마트홈 연동: 연동 경로 상태, 통합 기기 목록·제어, 확인 필요 알림."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import require_user
from ..connectors.base import describe
from ..connectors.homeassistant import HomeAssistant
from ..connectors.hubitat import Hubitat, normalize_device
from ..core import ctx, run_action
from .hubs import _homebridge, collect

router = APIRouter(prefix="/api/smarthome", tags=["smarthome"], dependencies=[Depends(require_user)])


async def _all_devices(request: Request) -> tuple[list[dict[str, Any]], list[str]]:
    s = ctx(request).settings
    errors: list[str] = []
    devices: list[dict[str, Any]] = []

    async def from_hub(cfg):
        if not cfg.maker_api:
            return []
        try:
            raw = await Hubitat(cfg).devices()
            return [normalize_device(cfg, d) for d in raw]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{cfg.name}: {describe(exc)}")
            return []

    async def from_ha():
        if not s.home_assistant:
            return []
        try:
            return await HomeAssistant(s.home_assistant).devices()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Home Assistant: {describe(exc)}")
            return []

    async def hb_names():
        if not s.homebridge:
            return set()
        try:
            return await _homebridge(request).accessory_names()
        except Exception:  # noqa: BLE001
            return set()

    results = await asyncio.gather(*(from_hub(h) for h in s.hubitat), from_ha(), hb_names())
    names: set[str] = results[-1]
    for chunk in results[:-1]:
        devices.extend(chunk)
    for d in devices:
        d["sources"] = [d["source"]] + (["HB"] if d["label"] in names else [])
    devices.sort(key=lambda d: (d["room"], d["label"]))
    return devices, errors


def _path_status(check_ref: str, systems: dict[str, Any]) -> str:
    if not check_ref:
        return "unchecked"
    if check_ref.startswith("hubitat:"):
        hub_id = check_ref.split(":", 1)[1]
        hub = next((h for h in systems["hubitat"] if (h["data"] or {}).get("id") == hub_id), None)
        if not hub:
            return "unknown"
        return "ok" if hub["online"] else "down"
    key = {"homeassistant": "home_assistant", "homebridge": "homebridge"}.get(check_ref)
    if not key:
        return "unknown"
    sysinfo = systems[key]
    if not sysinfo["configured"]:
        return "unknown"
    return "ok" if sysinfo["online"] else "down"


@router.get("")
async def overview(request: Request) -> dict:
    c = ctx(request)
    s = c.settings
    primary = next((h for h in s.hubitat if h.maker_api), None)

    async def mode_hsm():
        if not primary:
            return {"mode": None, "hsm": None}
        try:
            return await Hubitat(primary).mode_and_hsm()
        except Exception:  # noqa: BLE001
            return {"mode": None, "hsm": None}

    (devices, errors), systems, mh = await asyncio.gather(_all_devices(request), collect(request), mode_hsm())

    paths = []
    for p in c.db.list("integration_paths"):
        paths.append({**p, "status": _path_status(p["check_ref"], systems)})

    alerts: list[dict[str, Any]] = []
    low = [d for d in devices if d["battery"] is not None and d["battery"] < s.alerts.battery_warn]
    if low:
        alerts.append({
            "kind": "warn", "title": f"배터리 {s.alerts.battery_warn}% 미만 {len(low)}개",
            "body": " · ".join(f"{d['label']} {d['battery']}%" for d in sorted(low, key=lambda x: x["battery"])[:6]),
        })
    opened = [d for d in devices if d["contact_open"]]
    if opened and (mh.get("mode") or "").lower() in ("away", "외출", "night", "취침"):
        alerts.append({
            "kind": "warn", "title": f"{mh['mode']} 모드인데 열린 문 {len(opened)}곳",
            "body": ", ".join(d["label"] for d in opened[:8]),
        })
    for h in systems["hubitat"]:
        if not h["online"]:
            alerts.append({"kind": "down", "title": f"{h['data']['name']} 응답 없음", "body": h["error"] or ""})
    for err in errors:
        alerts.append({"kind": "down", "title": "기기 목록을 가져오지 못함", "body": err})

    return {
        "mode": mh.get("mode"), "hsm": mh.get("hsm"),
        "paths": paths, "devices": devices, "alerts": alerts,
        # 기기를 가져올 수 있는 연결이 있는지 (없으면 화면은 "연결하기" 안내)
        "sources": {"hubitat": sum(1 for h in s.hubitat if h.maker_api), "home_assistant": bool(s.home_assistant)},
    }


@router.post("/devices/{source}/{hub}/{device_id}/{command}")
async def device_command(source: str, hub: str, device_id: str, command: str, request: Request) -> dict:
    c = ctx(request)
    if command not in ("on", "off"):
        raise HTTPException(400, "켜기/끄기만 지원합니다")
    if source == "HE":
        cfg = c.settings.hub(hub)
        if not cfg:
            raise HTTPException(404, "등록되지 않은 허브입니다")
        return await run_action(c, f"기기 {command}", f"{hub}/{device_id}", Hubitat(cfg).command(device_id, command))
    if source == "HA":
        if not c.settings.home_assistant:
            raise HTTPException(404, "Home Assistant 연결 설정이 없습니다")
        return await run_action(c, f"기기 {command}", device_id,
                                HomeAssistant(c.settings.home_assistant).command(device_id, command))
    raise HTTPException(400, "알 수 없는 출처")
