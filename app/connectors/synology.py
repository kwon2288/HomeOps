"""Synology DSM Web API.

2단계 인증(OTP)을 켠 계정은 처음 한 번 OTP 코드로 로그인하면서 HomeOps를 "신뢰할 수 있는 기기"로
등록하고(device token), 이후에는 그 기기 ID로 코드 없이 로그인한다.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import SynologyCfg
from .base import ConnectorError, make_client

DEVICE_NAME = "HomeOps"
LOGIN_ERRORS = {
    400: "아이디 또는 비밀번호가 맞지 않습니다",
    401: "계정이 비활성화되어 있습니다",
    402: "권한이 없는 계정입니다",
    403: "2단계 인증 코드(OTP)가 필요합니다. 인증 앱의 6자리 코드를 넣고 연결 테스트 또는 저장을 누르세요",
    404: "2단계 인증 코드(OTP)가 맞지 않거나 만료되었습니다. 새 코드로 다시 시도하세요",
    406: "이 계정은 2단계 인증을 먼저 설정해야 합니다 (DSM에서 설정)",
    407: "로그인 시도가 많아 IP가 차단되었습니다 (DSM 보안 설정 확인)",
}


class Synology:
    def __init__(self, cfg: SynologyCfg, otp_code: str = "", device_id: str = ""):
        self.cfg = cfg
        self.base = cfg.url.rstrip("/")
        self.otp_code = otp_code.strip()
        self.device_id = device_id
        self.new_device_id: str | None = None   # OTP 로그인으로 새로 받은 기기 ID

    async def _login(self, c: httpx.AsyncClient) -> str:
        params = {
            "api": "SYNO.API.Auth", "version": "6", "method": "login",
            "account": self.cfg.username, "passwd": self.cfg.password,
            "session": "HomeOps", "format": "sid",
        }
        if self.otp_code:
            params.update(otp_code=self.otp_code, enable_device_token="yes", device_name=DEVICE_NAME)
        elif self.device_id:
            params.update(device_id=self.device_id, device_name=DEVICE_NAME, enable_device_token="yes")
        r = await c.get(f"{self.base}/webapi/auth.cgi", params=params)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            code = (data.get("error") or {}).get("code")
            if code == 403 and self.device_id and not self.otp_code:
                raise ConnectorError("저장된 기기 등록이 해제되었습니다. OTP 코드를 다시 넣고 저장하세요")
            raise ConnectorError(LOGIN_ERRORS.get(code, f"DSM 로그인 실패 (코드 {code})"))
        # 기기 토큰: DSM 6 은 did, DSM 7 은 device_id
        token = data["data"].get("device_id") or data["data"].get("did")
        if self.otp_code and token:
            self.new_device_id = token
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
