"""Homey Pro 로컬 Web API (API 키).

Homey 웹 앱 → 설정 → API Keys 에서 만든 키를 `Authorization: Bearer <키>` 로 보낸다.
- 기기:   GET  /api/manager/devices/device/                          (id → 기기)
- 제어:   PUT  /api/manager/devices/device/{id}/capability/{cap}/    {"value": …} (JSON으로 보내야 타입이 맞음)
- 구역:   GET  /api/manager/zones/zone/
- 플로우: GET  /api/manager/flow/flow/ · /api/manager/flow/advancedflow/
          POST /api/manager/flow/flow/{id}/trigger · /api/manager/flow/advancedflow/{id}/trigger
- 시스템: GET  /api/manager/system/  (키에 시스템 읽기 권한이 있을 때만)
Homey Pro (Early 2019) 이하는 API 키가 없어 쓸 수 없다.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from .base import ConnectorError, make_client

SAFE_ID = re.compile(r"^[A-Za-z0-9\-]{1,64}$")
SAFE_CAP = re.compile(r"^[a-z][a-z0-9_.\-]{0,60}$")


def _items(data: Any) -> list[dict[str, Any]]:
    """Homey는 목록을 {id: 객체} 로 준다 (버전에 따라 배열일 수도)."""
    if isinstance(data, dict):
        return [v for v in data.values() if isinstance(v, dict)]
    return [v for v in data or [] if isinstance(v, dict)]


class Homey:
    def __init__(self, url: str, api_key: str, verify_ssl: bool = False):
        if not api_key:
            raise ConnectorError("API 키를 입력하세요")
        self.base = url.rstrip("/") + "/api/manager"
        self.headers = {"Authorization": f"Bearer {api_key.strip()}"}
        self.verify = verify_ssl

    def _client(self) -> httpx.AsyncClient:
        return make_client(verify=self.verify, headers=self.headers, timeout=10.0)

    async def _get(self, c: httpx.AsyncClient, path: str) -> Any:
        r = await c.get(f"{self.base}{path}")
        if r.status_code in (401, 403):
            raise ConnectorError("인증 실패 — API 키가 맞는지, 키에 이 정보를 읽을 권한이 있는지 확인하세요")
        r.raise_for_status()
        return r.json()

    async def snapshot(self, with_flows: bool = False) -> dict[str, Any]:
        async with self._client() as c:
            devices = _items(await self._get(c, "/devices/device/"))

            async def optional(path: str) -> Any:
                # 구역 · 플로우 · 시스템은 키 권한에 따라 막혀 있을 수 있음 → 없으면 빈 값
                try:
                    return await self._get(c, path)
                except (ConnectorError, httpx.HTTPError, ValueError):
                    return None
            zones, system, flows, aflows = await asyncio.gather(
                optional("/zones/zone/"), optional("/system/"),
                optional("/flow/flow/") if with_flows else asyncio.sleep(0),
                optional("/flow/advancedflow/") if with_flows else asyncio.sleep(0),
            )
        zone_names = {z.get("id"): z.get("name") for z in _items(zones)}
        flow_list = [{"id": f.get("id"), "name": f.get("name"), "kind": "flow", "enabled": f.get("enabled", True)}
                     for f in _items(flows)] + \
                    [{"id": f.get("id"), "name": f.get("name"), "kind": "advancedflow", "enabled": f.get("enabled", True)}
                     for f in _items(aflows)]
        return {"devices": devices, "zones": zone_names, "system": system if isinstance(system, dict) else {},
                "flows": [f for f in flow_list if f["id"] and f["enabled"] is not False]}

    async def set_capability(self, device_id: str, capability: str, value: Any) -> None:
        if not SAFE_ID.match(device_id) or not SAFE_CAP.match(capability):
            raise ConnectorError("잘못된 기기 ID 또는 기능")
        async with self._client() as c:
            r = await c.put(f"{self.base}/devices/device/{device_id}/capability/{capability}/", json={"value": value})
            if r.status_code in (401, 403):
                raise ConnectorError("권한 없음 — API 키에 기기 제어 권한이 있는지 확인하세요")
            r.raise_for_status()

    async def trigger_flow(self, flow_id: str, kind: str) -> None:
        if not SAFE_ID.match(flow_id) or kind not in ("flow", "advancedflow"):
            raise ConnectorError("잘못된 플로우")
        async with self._client() as c:
            r = await c.post(f"{self.base}/flow/{kind}/{flow_id}/trigger")
            if r.status_code in (401, 403):
                raise ConnectorError("권한 없음 — API 키에 플로우 실행 권한이 있는지 확인하세요")
            r.raise_for_status()


def cap(d: dict[str, Any], name: str) -> Any:
    o = (d.get("capabilitiesObj") or {}).get(name)
    return o.get("value") if isinstance(o, dict) else None


def setable(d: dict[str, Any], name: str) -> bool:
    o = (d.get("capabilitiesObj") or {}).get(name)
    return isinstance(o, dict) and o.get("setable", True) is not False and name in (d.get("capabilities") or [name])


def app_of(d: dict[str, Any]) -> str:
    """기기를 만든 Homey 앱 id (예: com.lgthinq). driverId · ownerUri 에서 꺼낸다."""
    for key in ("driverId", "driverUri", "ownerUri"):
        v = str(d.get(key) or "")
        m = re.match(r"homey:app:([^:]+)", v)
        if m:
            return m.group(1)
    return ""
