"""UniFi Network (UniFi OS 콘솔: UDR, UDM, Cloud Key 등) — 공식 Integration API v1.

API 키: UniFi Network → Settings → Control Plane → Integrations (버전에 따라 Settings → Integrations)
요청: {콘솔}/proxy/network/integration/v1/... , 헤더 X-API-Key
"""
from __future__ import annotations

import re

import httpx

from ..connectors.base import ConnectorError, make_client
from .base import Integration, act, card, field, metric, row, section, url_field, verify_field

SAFE_ID = re.compile(r"^[A-Za-z0-9\-]{1,64}$")
STATE = {"ONLINE": ("온라인", "ok"), "OFFLINE": ("오프라인", "warn"), "PENDING_ADOPTION": ("채택 대기", "warn"),
         "UPDATING": ("업데이트 중", ""), "GETTING_READY": ("준비 중", ""), "ADOPTING": ("채택 중", ""),
         "DELETING": ("삭제 중", ""), "CONNECTION_INTERRUPTED": ("연결 끊김", "warn"), "ISOLATED": ("격리됨", "warn")}


class UniFiNetwork(Integration):
    type = "unifi"
    title = "UniFi Network"
    category = "infra"
    desc = "게이트웨이 · 스위치 · AP 상태 · 장치 재시작"
    order = 40
    help = ("UniFi 콘솔(UDR 등)의 Network 앱 → Settings → <b>Integrations</b>(버전에 따라 Control Plane → Integrations)에서 "
            "API 키를 만드세요. 주소는 콘솔 주소 그대로(예: <code>https://192.168.0.1</code>) 넣습니다. "
            "사이트를 비워 두면 첫 번째 사이트를 씁니다.")
    fields = [
        url_field("https://192.168.0.1"),
        field("api_key", "API 키", secret=True, required=True, full=True),
        field("site", "사이트 이름 (선택)", ph="비워 두면 첫 번째 사이트"),
        verify_field(default=False),
    ]

    def _base(self) -> str:
        return self.cfg["url"].rstrip("/") + "/proxy/network/integration/v1"

    def _client(self) -> httpx.AsyncClient:
        return make_client(verify=self.cfg.get("verify_ssl", False), timeout=10,
                           headers={"X-API-Key": self.cfg.get("api_key") or "", "Accept": "application/json"})

    async def _get(self, c: httpx.AsyncClient, path: str, **params):
        r = await c.get(self._base() + path, params=params or None)
        if r.status_code in (401, 403):
            raise ConnectorError("UniFi API 키 인증 실패")
        if r.status_code == 404:
            raise ConnectorError("UniFi Integration API를 찾지 못했습니다 (콘솔 주소와 Network 앱 버전 확인)")
        r.raise_for_status()
        return r.json()

    async def _list(self, c: httpx.AsyncClient, path: str) -> tuple[list[dict], int]:
        """offset/limit 페이지를 모두 모은다 (최대 1000개)."""
        items: list[dict] = []
        total = 0
        offset = 0
        while True:
            data = await self._get(c, path, offset=offset, limit=200)
            page = data.get("data", []) if isinstance(data, dict) else data
            total = data.get("totalCount", len(page)) if isinstance(data, dict) else len(page)
            items.extend(page)
            offset += len(page)
            if not page or offset >= total or offset >= 1000:
                return items, total

    async def _site(self, c: httpx.AsyncClient) -> dict:
        sites, _ = await self._list(c, "/sites")
        if not sites:
            raise ConnectorError("사이트가 없습니다")
        want = (self.cfg.get("site") or "").strip().lower()
        if want:
            for s in sites:
                if want in (str(s.get("name", "")).lower(), str(s.get("internalReference", "")).lower(), str(s.get("id", "")).lower()):
                    return s
            raise ConnectorError(f"'{self.cfg['site']}' 사이트를 찾지 못했습니다")
        return sites[0]

    async def status(self) -> dict:
        async with self._client() as c:
            try:
                info = await self._get(c, "/info")
            except ConnectorError:
                raise
            except httpx.HTTPError:
                info = {}
            site = await self._site(c)
            sid = site["id"]
            devices, _ = await self._list(c, f"/sites/{sid}/devices")
            try:
                clients = await self._get(c, f"/sites/{sid}/clients", limit=1)
                client_total = clients.get("totalCount") if isinstance(clients, dict) else None
            except (ConnectorError, httpx.HTTPError):
                client_total = None
        online = sum(1 for d in devices if d.get("state") == "ONLINE")
        rows = []
        for d in sorted(devices, key=lambda x: (x.get("state") == "ONLINE", x.get("name") or "")):
            label, tone = STATE.get(d.get("state", ""), (d.get("state") or "—", ""))
            note = " · ".join(str(x) for x in (d.get("model"), d.get("ipAddress"), d.get("firmwareVersion")) if x)
            rows.append(row(d.get("name") or d.get("macAddress") or d.get("id"), note, badge=label, tone=tone,
                            actions=[act("restart", "재시작", params={"device": d["id"]},
                                         confirm=f"{d.get('name') or '이 장치'}를 재시작합니다. 연결된 기기의 네트워크가 잠시 끊깁니다.")]
                            if d.get("id") else []))
        ver = info.get("applicationVersion") if isinstance(info, dict) else None
        return card(
            summary=" · ".join(x for x in (f"Network {ver}" if ver else "", f"사이트 {site.get('name') or site.get('internalReference') or ''}") if x),
            metrics=[metric("장치", len(devices)), metric("온라인", f"{online} / {len(devices)}"),
                     metric("클라이언트", client_total), metric("오프라인", len(devices) - online)],
            sections=[section("장치 (문제 있는 것 먼저)", rows, empty="채택된 장치가 없습니다")],
        )

    async def test(self) -> str:
        async with self._client() as c:
            site = await self._site(c)
            devices, _ = await self._list(c, f"/sites/{site['id']}/devices")
        return f"연결됨 · 사이트 {site.get('name') or site.get('internalReference')} · 장치 {len(devices)}개"

    async def action(self, action: str, params: dict):
        if action == "restart":
            dev = str(params.get("device", ""))
            if not SAFE_ID.match(dev):
                raise ConnectorError("작업 대상이 올바르지 않습니다")
            async with self._client() as c:
                site = await self._site(c)
                r = await c.post(f"{self._base()}/sites/{site['id']}/devices/{dev}/actions", json={"action": "RESTART"})
                if r.status_code in (401, 403):
                    raise ConnectorError("UniFi API 키에 장치 제어 권한이 없습니다")
                r.raise_for_status()
            return "재시작을 요청했습니다"
        return await super().action(action, params)
