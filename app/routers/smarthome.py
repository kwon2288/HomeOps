"""스마트홈 연동: 연동 경로 상태, 통합 기기 목록·제어, 확인 필요 알림."""
import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import integrations
from ..auth import require_user
from ..connectors.base import ConnectorError, describe
from ..core import ctx, run_action
from .connections import instance, statuses

router = APIRouter(prefix="/api/smarthome", tags=["smarthome"], dependencies=[Depends(require_user)])
# 예전 버전의 상태 확인 대상 표기 → 연결 id
LEGACY_REFS = {"homeassistant": "home-assistant"}
DEVICES_TIMEOUT = 50
_last_devices: dict[str, tuple[float, list]] = {}   # 연결 id → (받은 시각, 기기 목록)


def _ref(check_ref: str) -> str:
    ref = check_ref.split(":", 1)[1] if check_ref.startswith("hubitat:") else check_ref
    return LEGACY_REFS.get(ref, ref)


@router.get("")
async def overview(request: Request) -> dict:
    c = ctx(request)
    s = c.settings
    sources = [x for x in s.connections if (cls := integrations.get(x.type)) and cls.provides_devices]
    bridges = [x for x in s.connections if x.type == "homebridge"]
    errors: list[str] = []
    stale: list[str] = []

    async def devices_of(conn):
        try:
            lst = await asyncio.wait_for(instance(request, conn).devices(), DEVICES_TIMEOUT)
            _last_devices[conn.id] = (time.time(), lst)
            return lst
        except Exception as exc:  # noqa: BLE001
            msg = f"{DEVICES_TIMEOUT}초 안에 끝나지 않았습니다" if isinstance(exc, asyncio.TimeoutError) else describe(exc)
            cached = _last_devices.get(conn.id)
            if cached:  # 한 번 느렸다고 기기가 다 사라지지 않게, 마지막으로 받은 목록을 보여 준다
                mins = max(1, round((time.time() - cached[0]) / 60))
                stale.append(f"{conn.name}: {msg} · {mins}분 전에 받은 목록을 보여 줍니다")
                return cached[1]
            errors.append(f"{conn.name}: {msg}")
            return []

    async def names_of(conn):
        try:
            return await asyncio.wait_for(instance(request, conn).accessory_names(), 15)
        except Exception:  # noqa: BLE001
            return set()

    async def mode_hsm():
        for conn in sources:
            try:
                mh = await asyncio.wait_for(instance(request, conn).mode_hsm(), 10)
            except Exception:  # noqa: BLE001
                continue
            if mh.get("mode") or mh.get("hsm"):
                return mh
        return {}

    paths = c.db.list("integration_paths")
    refs = {_ref(p["check_ref"]) for p in paths if p["check_ref"]}
    need_status = [x for x in s.connections if x.id in refs]

    async def ref_status():
        if not need_status:
            return {}
        all_st = await statuses(request)
        return {st["id"]: st for st in all_st if st["id"] in refs}

    results = await asyncio.gather(
        asyncio.gather(*(devices_of(x) for x in sources)),
        asyncio.gather(*(names_of(x) for x in bridges)),
        mode_hsm(), ref_status(),
    )
    device_lists, name_sets, mh, ref_st = results
    names: set[str] = set().union(*name_sets) if name_sets else set()
    devices: list[dict[str, Any]] = [d for lst in device_lists for d in lst]
    for d in devices:
        d["sources"] = [d["source"]] + (["HB"] if d["label"] in names else [])
    devices.sort(key=lambda d: (d["room"], d["label"]))

    out_paths = []
    for p in paths:
        ref = _ref(p["check_ref"]) if p["check_ref"] else ""
        if not ref:
            status = "unchecked"
        elif ref not in ref_st:
            status = "unknown"
        else:
            status = "ok" if ref_st[ref]["online"] else "down"
        out_paths.append({**p, "check_ref": ref, "status": status})

    alerts: list[dict[str, Any]] = []
    warn = s.alerts.battery_warn
    low = [d for d in devices if d["battery"] is not None and d["battery"] < warn]
    if low:
        alerts.append({"kind": "warn", "title": f"배터리 {warn}% 미만 {len(low)}개",
                       "body": " · ".join(f"{d['label']} {d['battery']}%" for d in sorted(low, key=lambda x: x["battery"])[:6])})
    opened = [d for d in devices if d["contact_open"]]
    if opened and (mh.get("mode") or "").lower() in ("away", "외출", "night", "취침"):
        alerts.append({"kind": "warn", "title": f"{mh['mode']} 모드인데 열린 문 {len(opened)}곳",
                       "body": ", ".join(d["label"] for d in opened[:8])})
    for err in errors:
        alerts.append({"kind": "down", "title": "기기 목록을 가져오지 못함", "body": err})
    for msg in stale:
        alerts.append({"kind": "warn", "title": "기기 목록 응답이 느림", "body": msg})

    return {
        "mode": mh.get("mode"), "hsm": mh.get("hsm"),
        "paths": out_paths, "devices": devices, "alerts": alerts,
        "sources": [{"id": x.id, "name": x.name, "type": x.type} for x in sources],
    }


@router.post("/devices/{conn_id}/{device_id}/{command}")
async def device_command(conn_id: str, device_id: str, command: str, request: Request) -> dict:
    c = ctx(request)
    if command not in ("on", "off"):
        raise HTTPException(400, "켜기/끄기만 지원합니다")
    conn = c.settings.conn(conn_id)
    if not conn:
        raise HTTPException(404, "연결이 없습니다")
    inst = instance(request, conn)
    if not inst.provides_devices:
        raise HTTPException(400, "기기 제어를 지원하지 않는 연결입니다")
    try:
        return await run_action(c, f"기기 {command}", f"{conn.name}/{device_id}", inst.command(device_id, command))
    except ConnectorError as exc:
        raise HTTPException(400, str(exc)) from exc
