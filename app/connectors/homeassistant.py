"""Home Assistant REST API (Long-Lived Access Token)."""
from __future__ import annotations

import re
from typing import Any

import httpx

from ..config import HomeAssistantCfg
from .base import ConnectorError, make_client

SWITCH_DOMAINS = {"switch", "light", "fan", "input_boolean"}
SAFE_ENTITY = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


class HomeAssistant:
    def __init__(self, cfg: HomeAssistantCfg):
        self.cfg = cfg
        self.base = cfg.url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {cfg.token}", "Content-Type": "application/json"}

    def _client(self, timeout: float = 8.0) -> httpx.AsyncClient:
        return make_client(verify=self.cfg.verify_ssl, timeout=timeout, headers=self.headers)

    async def _states(self, c: httpx.AsyncClient) -> list[dict[str, Any]]:
        r = await c.get(f"{self.base}/api/states")
        r.raise_for_status()
        return r.json()

    async def status(self) -> dict[str, Any]:
        async with self._client() as c:
            r = await c.get(f"{self.base}/api/config")
            r.raise_for_status()
            cfg = r.json()
            states = await self._states(c)
        updates = [s for s in states if s["entity_id"].startswith("update.") and s.get("state") == "on"]
        return {
            "online": True,
            "version": cfg.get("version"),
            "location": cfg.get("location_name"),
            "entity_count": len(states),
            "update_count": len(updates),
        }

    async def devices(self) -> list[dict[str, Any]]:
        async with self._client() as c:
            states = await self._states(c)
        out = []
        for s in states:
            domain = s["entity_id"].split(".", 1)[0]
            attrs = s.get("attributes") or {}
            name = attrs.get("friendly_name") or s["entity_id"]
            if domain in SWITCH_DOMAINS:
                out.append({
                    "source": "HA", "hub": "ha", "hub_name": "Home Assistant", "id": s["entity_id"],
                    "label": name, "room": "Home Assistant", "is_switch": True, "on": s.get("state") == "on",
                    "state_label": None, "tone": "plain", "detail": domain, "battery": None,
                    "contact_open": False,
                })
            elif domain == "lock":
                out.append({
                    "source": "HA", "hub": "ha", "hub_name": "Home Assistant", "id": s["entity_id"],
                    "label": name, "room": "Home Assistant", "is_switch": False, "on": False,
                    "state_label": {"locked": "잠김", "unlocked": "열림"}.get(s.get("state"), s.get("state")),
                    "tone": "ok" if s.get("state") == "locked" else "warn", "detail": "lock",
                    "battery": None, "contact_open": False,
                })
        return out

    async def command(self, entity_id: str, command: str) -> None:
        if not SAFE_ENTITY.match(entity_id) or command not in ("on", "off"):
            raise ConnectorError("잘못된 엔티티 또는 명령")
        service = "turn_on" if command == "on" else "turn_off"
        async with self._client() as c:
            r = await c.post(f"{self.base}/api/services/homeassistant/{service}", json={"entity_id": entity_id})
            r.raise_for_status()

    async def restart(self) -> None:
        async with self._client() as c:
            try:
                r = await c.post(f"{self.base}/api/services/homeassistant/restart", json={})
                r.raise_for_status()
            except httpx.ReadTimeout:
                pass  # 재시작 중이라 응답 없이 끊기는 경우가 많다

    async def backup(self) -> str:
        """HA OS(Supervisor) 전체 백업. 오래 걸리므로 시작 요청까지만 기다린다."""
        async with self._client(timeout=15.0) as c:
            try:
                r = await c.post(f"{self.base}/api/services/hassio/backup_full", json={})
                r.raise_for_status()
                return "백업 완료"
            except httpx.ReadTimeout:
                return "백업 시작됨 (진행 중)"
