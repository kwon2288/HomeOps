"""Hubitat Elevation.

- 기기 목록·제어·모드·HSM: Maker API (공식)
- 메모리·온도·DB 크기·재부팅·백업: 허브 관리 화면이 쓰는 URL (비공식, 펌웨어 변경 시 달라질 수 있음)
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from ..config import HubitatCfg
from .base import ConnectorError, make_client

SAFE_COMMAND = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,40}$")
SAFE_ID = re.compile(r"^\d{1,8}$")
PROBE_TIMEOUT = httpx.Timeout(8.0, connect=4.0)
# /devices/all 은 고른 기기 전체의 속성까지 보내서, 기기가 많은 허브에서는 수십 초 걸리기도 한다
FULL_LIST_TIMEOUT = httpx.Timeout(45.0, connect=4.0)


class Hubitat:
    def __init__(self, cfg: HubitatCfg):
        self.cfg = cfg
        self.base = cfg.url.rstrip("/")

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[httpx.AsyncClient]:
        """허브에 닿는지 확인하고, 허브 로그인을 켰으면 로그인까지 한 연결."""
        async with make_client() as client:
            await self._probe(client)
            if self.cfg.login:
                await client.post(
                    f"{self.base}/login",
                    data={"username": self.cfg.login.username, "password": self.cfg.login.password, "submit": "Login"},
                )
            yield client

    async def _probe(self, c: httpx.AsyncClient) -> httpx.Response:
        """허브에 닿는지 먼저 짧게 확인한다. 안 닿으면 여러 요청을 기다리지 않고 바로 이유를 알려 준다."""
        host = self.base.split("://", 1)[-1]
        try:
            return await c.get(f"{self.base}/hub2/hubData", timeout=PROBE_TIMEOUT)
        except httpx.ConnectTimeout as exc:
            raise ConnectorError(f"허브({host})가 {PROBE_TIMEOUT.connect:.0f}초 안에 연결을 받지 않습니다 — IP 주소가 맞는지, "
                                 "허브가 켜져 있는지, HomeOps가 그 네트워크에 닿는지 확인하세요") from exc
        except httpx.ConnectError as exc:
            raise ConnectorError(f"허브({host})에 연결할 수 없습니다 — 주소와 포트를 확인하세요") from exc
        except httpx.TimeoutException as exc:
            raise ConnectorError(f"허브({host})에 연결은 됐지만 /hub2/hubData 요청에 {PROBE_TIMEOUT.read:.0f}초 동안 "
                                 "응답이 없습니다") from exc

    def _maker(self, path: str) -> tuple[str, dict[str, str]]:
        if not self.cfg.maker_api:
            raise ConnectorError("Maker API 설정이 없습니다")
        url = f"{self.base}/apps/api/{self.cfg.maker_api.app_id}{path}"
        return url, {"access_token": self.cfg.maker_api.token}

    @staticmethod
    async def _text(client: httpx.AsyncClient, url: str) -> str | None:
        try:
            r = await client.get(url)
            r.raise_for_status()
            text = r.text.strip()
            if text.startswith("<"):  # 로그인 페이지로 돌려보낸 경우
                return None
            return text
        except httpx.HTTPError:
            return None

    @staticmethod
    def _num(text: str | None) -> float | None:
        if text is None:
            return None
        m = re.search(r"-?\d+(\.\d+)?", text)
        return float(m.group()) if m else None

    async def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.cfg.id, "name": self.cfg.name, "url": self.cfg.url, "role": self.cfg.role,
            "online": False, "free_memory_kb": None, "temperature_c": None, "database_mb": None,
            "firmware": None, "device_count": None,
        }
        async with self._session() as c:   # 여기서 허브에 안 닿으면 바로 이유와 함께 실패
            async def fw() -> None:
                try:
                    r = await c.get(f"{self.base}/hub2/hubData")
                    if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                        data = r.json()
                        out["firmware"] = data.get("firmwareVersionString") or data.get("version")
                except (httpx.HTTPError, ValueError):
                    pass

            async def count() -> None:
                if not self.cfg.maker_api:
                    return
                try:
                    out["device_count"] = len(await self.device_ids(c))
                except (httpx.HTTPError, ConnectorError, ValueError):
                    pass

            # 여러 요청을 한꺼번에 (하나씩 기다리면 느린 허브에서 전체 시간 초과가 남)
            mem, temp, db, *_ = await asyncio.gather(
                self._text(c, f"{self.base}/hub/advanced/freeOSMemory"),
                self._text(c, f"{self.base}/hub/advanced/internalTempCelsius"),
                self._text(c, f"{self.base}/hub/advanced/databaseSize"),
                fw(), count(),
            )
            mem, temp, db = self._num(mem), self._num(temp), self._num(db)
            out["free_memory_kb"] = int(mem) if mem is not None else None
            out["temperature_c"] = temp
            out["database_mb"] = db
            out["online"] = any(v is not None for v in (mem, temp, db)) or out["device_count"] is not None
        return out

    async def device_ids(self, c: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
        """Maker API 의 가벼운 목록 (id · 이름만). 개수 확인 · 연결 테스트용."""
        url, params = self._maker("/devices")
        if c is None:
            async with make_client() as own:
                r = await own.get(url, params=params)
        else:
            r = await c.get(url, params=params)
        r.raise_for_status()
        return r.json()

    async def devices(self) -> list[dict[str, Any]]:
        """속성까지 포함한 전체 목록 (기기 화면용). 느릴 수 있어서 기다리는 시간을 길게."""
        url, params = self._maker("/devices/all")
        async with make_client() as c:
            r = await c.get(url, params=params, timeout=FULL_LIST_TIMEOUT)
            r.raise_for_status()
            return r.json()

    async def command(self, device_id: str, command: str, arg: str | None = None) -> None:
        if not SAFE_ID.match(device_id) or not SAFE_COMMAND.match(command):
            raise ConnectorError("잘못된 기기 ID 또는 명령")
        path = f"/devices/{device_id}/{command}"
        if arg is not None:
            if not re.match(r"^[\w.\-]{1,40}$", arg):
                raise ConnectorError("잘못된 명령 인자")
            path += f"/{arg}"
        url, params = self._maker(path)
        async with make_client() as c:
            r = await c.get(url, params=params)
            r.raise_for_status()

    async def mode_and_hsm(self) -> dict[str, Any]:
        out: dict[str, Any] = {"mode": None, "hsm": None}
        async with make_client() as c:
            try:
                url, params = self._maker("/modes")
                r = await c.get(url, params=params)
                r.raise_for_status()
                active = next((m for m in r.json() if m.get("active")), None)
                out["mode"] = active.get("name") if active else None
            except (httpx.HTTPError, ConnectorError, ValueError):
                pass
            try:
                url, params = self._maker("/hsm")
                r = await c.get(url, params=params)
                r.raise_for_status()
                out["hsm"] = r.json().get("hsm")
            except (httpx.HTTPError, ConnectorError, ValueError):
                pass
        return out

    async def reboot(self) -> None:
        async with self._session() as c:
            r = await c.post(f"{self.base}/hub/reboot")
            r.raise_for_status()

    async def backup(self, backup_dir: Path, keep: int) -> dict[str, Any]:
        backup_dir.mkdir(parents=True, exist_ok=True)
        async with self._session() as c:
            c.timeout = httpx.Timeout(180.0)
            r = await c.get(f"{self.base}/hub/backupDB", params={"fileName": "latest"})
            r.raise_for_status()
            if r.headers.get("content-type", "").startswith("text/html"):
                raise ConnectorError("백업 파일 대신 웹 페이지가 왔습니다 (허브 로그인 설정 확인)")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = backup_dir / f"{self.cfg.id}-{stamp}.lzf"
        path.write_bytes(r.content)
        old = sorted(backup_dir.glob(f"{self.cfg.id}-*.lzf"))
        for stale in old[:-keep] if keep > 0 else []:
            stale.unlink(missing_ok=True)
        return {"file": path.name, "size": len(r.content)}


def normalize_device(hub: HubitatCfg, d: dict[str, Any]) -> dict[str, Any]:
    """Maker API 기기 → 화면 공통 형식."""
    attrs = d.get("attributes") or {}
    if isinstance(attrs, list):  # 일부 펌웨어는 [{name, currentValue}] 형태
        attrs = {a.get("name"): a.get("currentValue") for a in attrs}
    commands = d.get("commands") or []
    command_names = {c if isinstance(c, str) else c.get("command") for c in commands}
    is_switch = "switch" in attrs and {"on", "off"} <= command_names
    state_label = None
    tone = "plain"
    if not is_switch:
        if "lock" in attrs:
            state_label = {"locked": "잠김", "unlocked": "열림"}.get(attrs["lock"], attrs["lock"])
            tone = "ok" if attrs["lock"] == "locked" else "warn"
        elif "contact" in attrs:
            state_label = {"open": "열림", "closed": "닫힘"}.get(attrs["contact"], attrs["contact"])
            tone = "warn" if attrs["contact"] == "open" else "ok"
        elif "motion" in attrs:
            state_label = {"active": "감지", "inactive": "없음"}.get(attrs["motion"], attrs["motion"])
        elif "temperature" in attrs:
            parts = [f"{attrs['temperature']}°"]
            if attrs.get("humidity") is not None:
                parts.append(f"{attrs['humidity']}%")
            state_label = " · ".join(parts)
        elif "presence" in attrs:
            state_label = {"present": "재실", "not present": "부재"}.get(attrs["presence"], attrs["presence"])
    detail = []
    if attrs.get("battery") is not None:
        detail.append(f"배터리 {attrs['battery']}%")
    if attrs.get("power") is not None:
        detail.append(f"{attrs['power']}W")
    battery = None
    try:
        battery = int(float(attrs["battery"])) if attrs.get("battery") is not None else None
    except (TypeError, ValueError):
        battery = None
    return {
        "source": "HE",
        "hub": hub.id,
        "hub_name": hub.name,
        "id": str(d.get("id")),
        "label": d.get("label") or d.get("name") or f"기기 {d.get('id')}",
        "room": d.get("room") or "미지정",
        "is_switch": is_switch,
        "on": attrs.get("switch") == "on",
        "state_label": state_label,
        "tone": tone,
        "detail": " · ".join(detail) or hub.name,
        "battery": battery,
        "contact_open": attrs.get("contact") == "open",
    }
