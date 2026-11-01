"""Homebridge config-ui-x REST API.

액세서리 목록(/api/accessories)은 Homebridge를 insecure 모드(-I)로 실행했을 때만 응답한다.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import HomebridgeCfg
from .base import ConnectorError, make_client


class Homebridge:
    def __init__(self, cfg: HomebridgeCfg):
        self.cfg = cfg
        self.base = cfg.url.rstrip("/")
        self._token: str | None = None
        self._token_exp = 0.0

    async def _auth(self, c: httpx.AsyncClient) -> dict[str, str]:
        if self._token and time.time() < self._token_exp - 60:
            return {"Authorization": f"Bearer {self._token}"}
        if self.cfg.username:
            r = await c.post(
                f"{self.base}/api/auth/login",
                json={"username": self.cfg.username, "password": self.cfg.password},
            )
        else:
            r = await c.post(f"{self.base}/api/auth/noauth")
        if r.status_code in (401, 403):
            raise ConnectorError("Homebridge 로그인 실패")
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + float(data.get("expires_in", 3600))
        return {"Authorization": f"Bearer {self._token}"}

    async def _get(self, c: httpx.AsyncClient, path: str) -> Any:
        r = await c.get(f"{self.base}{path}", headers=await self._auth(c))
        r.raise_for_status()
        return r.json()

    async def status(self) -> dict[str, Any]:
        async with make_client(verify=self.cfg.verify_ssl) as c:
            st = await self._get(c, "/api/status/homebridge")
            out: dict[str, Any] = {
                "online": True,
                # UI 버전에 따라 실행 중을 "up" 또는 "ok"로 알려 준다 ("pending" = 시작 중)
                "state": str(st.get("status") or "").lower(),
                "running": str(st.get("status") or "").lower() in ("up", "ok"),
                "version": None, "plugin_count": None, "accessory_count": None,
                "insecure_mode": False,
            }
            try:
                v = await self._get(c, "/api/status/homebridge-version")
                out["version"] = v.get("installedVersion")
            except httpx.HTTPError:
                pass
            try:
                out["plugin_count"] = len(await self._get(c, "/api/plugins"))
            except httpx.HTTPError:
                pass
            try:
                acc = await self._get(c, "/api/accessories")
                out["accessory_count"] = len(acc)
                out["insecure_mode"] = True
            except httpx.HTTPError:
                pass
        return out

    async def accessory_names(self) -> set[str]:
        async with make_client(verify=self.cfg.verify_ssl) as c:
            try:
                acc = await self._get(c, "/api/accessories")
            except httpx.HTTPError:
                return set()
        names = set()
        for a in acc:
            name = a.get("serviceName") or (a.get("accessoryInformation") or {}).get("Name")
            if name:
                names.add(name.strip())
        return names

    async def restart(self) -> None:
        async with make_client(verify=self.cfg.verify_ssl) as c:
            r = await c.put(f"{self.base}/api/server/restart", headers=await self._auth(c))
            r.raise_for_status()
