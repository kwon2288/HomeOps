"""Synology DSM Web API.

2단계 인증이 켜진 계정은 자동 로그인이 안 되므로 HomeOps 전용 계정을 만들어 쓴다.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import SynologyCfg
from .base import ConnectorError, make_client


class Synology:
    def __init__(self, cfg: SynologyCfg):
        self.cfg = cfg
        self.base = cfg.url.rstrip("/")

    async def _login(self, c: httpx.AsyncClient) -> str:
        r = await c.get(f"{self.base}/webapi/auth.cgi", params={
            "api": "SYNO.API.Auth", "version": "6", "method": "login",
            "account": self.cfg.username, "passwd": self.cfg.password,
            "session": "HomeOps", "format": "sid",
        })
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            code = (data.get("error") or {}).get("code")
            if code == 403:
                raise ConnectorError("2단계 인증이 필요한 계정입니다 (전용 계정 사용)")
            raise ConnectorError(f"DSM 로그인 실패 (코드 {code})")
        return data["data"]["sid"]

    async def _call(self, c: httpx.AsyncClient, sid: str, api: str, method: str, version: int = 1, **params) -> dict[str, Any]:
        r = await c.get(f"{self.base}/webapi/entry.cgi", params={
            "api": api, "version": str(version), "method": method, "_sid": sid, **params,
        })
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            raise ConnectorError(f"{api}.{method} 실패 (코드 {(data.get('error') or {}).get('code')})")
        return data.get("data") or {}

    async def _logout(self, c: httpx.AsyncClient, sid: str) -> None:
        try:
            await c.get(f"{self.base}/webapi/auth.cgi", params={
                "api": "SYNO.API.Auth", "version": "6", "method": "logout", "session": "HomeOps", "_sid": sid,
            })
        except httpx.HTTPError:
            pass

    async def status(self) -> dict[str, Any]:
        async with make_client(verify=self.cfg.verify_ssl) as c:
            sid = await self._login(c)
            try:
                info = await self._call(c, sid, "SYNO.Core.System", "info")
                util = await self._call(c, sid, "SYNO.Core.System.Utilization", "get")
                storage = await self._call(c, sid, "SYNO.Storage.CGI.Storage", "load_info")
            finally:
                await self._logout(c, sid)
        cpu = util.get("cpu") or {}
        mem = util.get("memory") or {}
        volumes = []
        for v in storage.get("volumes") or []:
            size = v.get("size") or {}
            total = float(size.get("total") or 0)
            used = float(size.get("used") or 0)
            volumes.append({
                "name": v.get("display_name") or v.get("id"),
                "status": v.get("status"),
                "used_pct": round(used / total * 100, 1) if total else None,
                "total_tb": round(total / 1e12, 2) if total else None,
            })
        disks = [{
            "name": d.get("name") or d.get("id"),
            "model": (d.get("model") or "").strip(),
            "status": d.get("status"),
            "smart": d.get("smart_status"),
            "temp": d.get("temp"),
        } for d in storage.get("disks") or []]
        bad = [d for d in disks if d["status"] not in (None, "normal") or d["smart"] not in (None, "normal", "safe")]
        return {
            "online": True,
            "model": info.get("model"),
            "version": info.get("firmware_ver"),
            "uptime": info.get("up_time"),
            "cpu_pct": (cpu.get("user_load") or 0) + (cpu.get("system_load") or 0),
            "mem_pct": mem.get("real_usage"),
            "volumes": volumes,
            "disks": disks,
            "disk_health": "정상" if disks and not bad else (f"주의 {len(bad)}개" if bad else None),
        }

    async def reboot(self) -> None:
        async with make_client(verify=self.cfg.verify_ssl) as c:
            sid = await self._login(c)
            await self._call(c, sid, "SYNO.Core.System", "reboot")
