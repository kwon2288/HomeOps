"""범용 웹 상태 확인 — 전용 연동이 없는 장비도 주소만으로 살아 있는지 보고 바로가기로 쓴다."""
from __future__ import annotations

import time

import httpx

from ..connectors.base import ConnectorError, make_client
from .base import Integration, card, field, metric, url_field, verify_field


class WebCheck(Integration):
    type = "web"
    title = "웹 상태 확인"
    category = "infra"
    desc = "전용 연동이 없는 장비 · 서비스의 응답 확인과 바로가기"
    order = 900
    help = ("전용 연동이 없는 장비나 서비스(공유기, 프린터, 웹 앱 등)의 웹 주소를 넣으면 응답 여부와 응답 시간을 보여 주고, "
            "카드에서 바로 열 수 있습니다. 로그인 화면(401·403)이 나와도 살아 있는 것으로 봅니다.")
    fields = [
        url_field("https://192.168.0.x:8443"),
        field("group", "표시할 메뉴", kind="select", default="infra",
              options=[("infra", "인프라"), ("smarthome", "스마트홈 허브")]),
        verify_field(default=False),
    ]

    @classmethod
    def category_of(cls, config: dict) -> str:
        return config.get("group") if config.get("group") in ("infra", "smarthome") else "infra"

    async def status(self) -> dict:
        start = time.monotonic()
        try:
            async with make_client(verify=self.cfg.get("verify_ssl", False), timeout=8) as c:
                r = await c.get(self.cfg["url"])
        except httpx.HTTPError as exc:
            raise ConnectorError(f"응답 없음 ({exc.__class__.__name__})") from exc
        ms = round((time.monotonic() - start) * 1000)
        alive = r.status_code < 500
        if not alive:
            raise ConnectorError(f"서버 오류 (HTTP {r.status_code})")
        return card(summary=f"HTTP {r.status_code} · {ms}ms",
                    metrics=[metric("응답 코드", r.status_code), metric("응답 시간", ms, unit="ms")])
