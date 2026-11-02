"""SwitchBot Open API v1.1 (클라우드).

- 인증: 앱의 개발자 옵션에서 받은 토큰 + 시크릿으로 요청마다 서명 (HMAC-SHA256)
- 하루 호출 한도가 10,000회라서 기기 목록 · 상태를 캐시한다 (상태는 기기마다 1회씩 들기 때문)
- 블루투스 기기(Bot · 커튼 · 도어락 등)는 허브(Hub 2 등)를 거쳐야 보이고, 앱에서 클라우드 서비스를 켜 둬야 한다
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import re
import time
import uuid
from datetime import date
from typing import Any

import httpx

from .base import ConnectorError, make_client

BASE = os.environ.get("HOMEOPS_SWITCHBOT_API", "https://api.switch-bot.com/v1.1")   # 바꾸는 건 테스트용
DAILY_LIMIT = 10_000
LIST_TTL = 3600                      # 기기 목록 · 장면은 자주 안 바뀜
SAFE_ID = re.compile(r"^[A-Za-z0-9\-]{1,64}$")

ERRORS = {
    151: "이 기기 종류에서는 지원하지 않는 요청입니다",
    152: "기기를 찾을 수 없습니다",
    160: "이 기기가 지원하지 않는 명령입니다",
    161: "기기가 오프라인입니다",
    171: "기기가 연결된 허브가 오프라인입니다",
    190: "기기 내부 오류 또는 잘못된 명령입니다",
}

# 상태 조회를 지원하는 종류 (IR 리모컨 · 카메라 등은 상태가 없음)
SWITCH_TYPES = {"Bot", "Plug", "Plug Mini (US)", "Plug Mini (JP)", "Plug Mini (EU)", "Relay Switch 1",
                "Relay Switch 1PM", "Color Bulb", "Strip Light", "Strip Light 3", "Ceiling Light",
                "Ceiling Light Pro", "Floor Lamp", "Candle Warmer Lamp", "RGBICWW Strip Light",
                "RGBICWW Floor Lamp", "RGBIC Neon Rope Light", "RGBIC Neon Wire Rope Light"}
CURTAIN_TYPES = {"Curtain", "Curtain3", "Roller Shade", "Blind Tilt"}
LOCK_TYPES = {"Smart Lock", "Smart Lock Pro", "Smart Lock Ultra", "Lock Vision", "Lock Vision Pro", "Lock Lite"}
NO_STATUS = {"Remote", "Indoor Cam", "Pan/Tilt Cam", "Pan/Tilt Cam 2K", "Keypad", "Keypad Touch", "Keypad Vision"}

# 같은 토큰을 쓰는 모든 화면이 한 캐시를 공유한다 (토큰 해시 → 데이터)
_cache: dict[str, dict[str, Any]] = {}
_calls: dict[str, tuple[date, int]] = {}   # 토큰 해시 → (날짜, 오늘 호출 수) — HomeOps가 센 값 (다시 시작하면 0부터)


def _key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def sign_headers(token: str, secret: str, t: int | None = None, nonce: str | None = None) -> dict[str, str]:
    t = t or int(time.time() * 1000)
    nonce = nonce or str(uuid.uuid4())
    digest = hmac.new(secret.encode(), f"{token}{t}{nonce}".encode(), hashlib.sha256).digest()
    return {"Authorization": token, "sign": base64.b64encode(digest).decode(), "t": str(t), "nonce": nonce,
            "Content-Type": "application/json; charset=utf8"}


class SwitchBot:
    def __init__(self, token: str, secret: str, status_ttl: int = 300):
        if not token or not secret:
            raise ConnectorError("토큰과 시크릿을 입력하세요")
        self.token, self.secret = token.strip(), secret.strip()
        self.status_ttl = status_ttl
        self.k = _key(self.token)
        self.cache = _cache.setdefault(self.k, {"devices": None, "scenes": None, "status": {}})

    # ---- 호출 ----

    def calls_today(self) -> int:
        d, n = _calls.get(self.k, (date.today(), 0))
        return n if d == date.today() else 0

    def _count(self) -> None:
        _calls[self.k] = (date.today(), self.calls_today() + 1)

    async def _req(self, c: httpx.AsyncClient, method: str, path: str, body: dict | None = None) -> Any:
        self._count()
        r = await c.request(method, f"{BASE}{path}", headers=sign_headers(self.token, self.secret), json=body)
        if r.status_code in (401, 403):
            raise ConnectorError("인증 실패 — 토큰 · 시크릿이 맞는지, 오늘 호출 한도(10,000회)를 넘지 않았는지 확인하세요")
        if r.status_code == 429:
            raise ConnectorError("SwitchBot 호출 한도를 넘었습니다. 잠시 뒤 다시 시도하세요")
        r.raise_for_status()
        data = r.json()
        code = data.get("statusCode")
        if code != 100:
            raise ConnectorError(ERRORS.get(code, f"SwitchBot 오류 {code}: {data.get('message') or ''}".strip()))
        return data.get("body") or {}

    def _client(self) -> httpx.AsyncClient:
        return make_client(timeout=10.0)

    # ---- 조회 ----

    async def devices(self, force: bool = False) -> dict[str, list[dict[str, Any]]]:
        """{"devices": [...], "remotes": [...]} — 1시간 캐시"""
        hit = self.cache["devices"]
        if hit and not force and time.time() - hit[0] < LIST_TTL:
            return hit[1]
        async with self._client() as c:
            body = await self._req(c, "GET", "/devices")
        out = {"devices": body.get("deviceList") or [], "remotes": body.get("infraredRemoteList") or []}
        self.cache["devices"] = (time.time(), out)
        return out

    async def scenes(self, force: bool = False) -> list[dict[str, Any]]:
        hit = self.cache["scenes"]
        if hit and not force and time.time() - hit[0] < LIST_TTL:
            return hit[1]
        async with self._client() as c:
            out = await self._req(c, "GET", "/scenes") or []
        self.cache["scenes"] = (time.time(), out)
        return out

    async def statuses(self, devices: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """기기별 상태 (캐시가 오래된 것만 새로 받음). 실패한 기기는 {"_error": 문장}."""
        now = time.time()
        st = self.cache["status"]
        need = [d for d in devices if has_status(d) and (d["deviceId"] not in st or now - st[d["deviceId"]][0] >= self.status_ttl)]
        if need:
            sem = asyncio.Semaphore(4)
            async with self._client() as c:
                async def one(d: dict[str, Any]) -> None:
                    async with sem:
                        try:
                            st[d["deviceId"]] = (time.time(), await self._req(c, "GET", f"/devices/{d['deviceId']}/status"))
                        except ConnectorError as exc:
                            st[d["deviceId"]] = (time.time(), {"_error": str(exc)})
                        except httpx.HTTPError as exc:
                            st[d["deviceId"]] = (time.time() - self.status_ttl + 30, {"_error": exc.__class__.__name__})
                await asyncio.gather(*(one(d) for d in need))
        return {k: v[1] for k, v in st.items()}

    # ---- 제어 ----

    async def command(self, device_id: str, command: str, parameter: Any = "default") -> None:
        if not SAFE_ID.match(device_id) or not re.match(r"^[A-Za-z]{2,30}$", command):
            raise ConnectorError("잘못된 기기 ID 또는 명령")
        async with self._client() as c:
            await self._req(c, "POST", f"/devices/{device_id}/commands",
                            {"command": command, "parameter": parameter, "commandType": "command"})
        self.cache["status"].pop(device_id, None)   # 다음 조회 때 새 상태를 받도록

    async def run_scene(self, scene_id: str) -> None:
        if not SAFE_ID.match(scene_id):
            raise ConnectorError("잘못된 장면 ID")
        async with self._client() as c:
            await self._req(c, "POST", f"/scenes/{scene_id}/execute")


def has_status(d: dict[str, Any]) -> bool:
    return d.get("deviceType") not in NO_STATUS and d.get("enableCloudService", True) is not False


def kind_of(device_type: str | None) -> str:
    t = device_type or ""
    if t in SWITCH_TYPES or t.startswith(("Plug", "Relay Switch")) or "Light" in t or "Lamp" in t or "Bulb" in t:
        return "switch"
    if t in CURTAIN_TYPES:
        return "curtain"
    if t in LOCK_TYPES or t.startswith("Smart Lock"):
        return "lock"
    if t.startswith(("Meter", "WoIOSensor", "Hub 2", "Hub 3", "Outdoor Meter")) or "Thermo" in t:
        return "meter"
    if t.startswith("Contact"):
        return "contact"
    if t.startswith("Motion") or t == "Presence Sensor":
        return "motion"
    if "Leak" in t or t == "Water Detector":
        return "leak"
    return "other"
