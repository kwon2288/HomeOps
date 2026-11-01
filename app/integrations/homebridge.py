"""Homebridge (config-ui-x)."""
from __future__ import annotations

from ..config import HomebridgeCfg
from ..connectors.homebridge import Homebridge as Client
from .base import Integration, act, card, field, metric, url_field, verify_field


class Homebridge(Integration):
    type = "homebridge"
    title = "Homebridge"
    category = "smarthome"
    desc = "HomeKit 노출 확인 · 재시작"
    order = 30
    help = ("Homebridge UI에 로그인하는 계정입니다. 기기 목록의 HomeKit 노출(HB) 표시와 액세서리 수는 "
            "Homebridge를 <b>insecure 모드(-I)</b>로 실행해야 보입니다.")
    fields = [
        url_field("http://192.168.0.x:8581"),
        field("username", "아이디", ph="admin"),
        field("password", "비밀번호", secret=True),
        verify_field(default=True),
    ]

    def _client(self) -> Client:
        return Client(HomebridgeCfg(url=self.cfg["url"], username=self.cfg.get("username") or "",
                                    password=self.cfg.get("password") or "", verify_ssl=self.cfg.get("verify_ssl", True)))

    async def status(self) -> dict:
        st = await self._client().status()
        return card(
            summary=f"Homebridge {st['version'] or '?'} · {'실행 중' if st['running'] else '정지'}",
            metrics=[metric("버전", st["version"]), metric("플러그인", st["plugin_count"]),
                     metric("액세서리", st["accessory_count"] if st["insecure_mode"] else "insecure 모드 필요"),
                     metric("상태", "실행 중" if st["running"] else "정지")],
            actions=[act("restart", "재시작", danger=True,
                         confirm="재시작하는 동안 HomeKit에서 Homebridge 기기가 응답 없음으로 보입니다.")],
        )

    async def action(self, action: str, params: dict):
        if action == "restart":
            await self._client().restart()
            return "재시작을 요청했습니다"
        return await super().action(action, params)

    async def accessory_names(self) -> set[str]:
        return await self._client().accessory_names()
