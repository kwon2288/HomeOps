"""Home Assistant (REST API, 장기 액세스 토큰)."""
from __future__ import annotations

from ..config import HomeAssistantCfg
from ..connectors.homeassistant import HomeAssistant as Client
from .base import Integration, act, card, field, metric, url_field, verify_field


class HomeAssistant(Integration):
    type = "home_assistant"
    title = "Home Assistant"
    category = "smarthome"
    desc = "엔티티 제어 · 백업 · 재시작"
    order = 20
    provides_devices = True
    help = "HA 프로필 → 보안 → <b>장기 액세스 토큰</b>을 만들어 붙여 넣으세요. 백업은 HA OS(Supervisor) 전체 백업을 씁니다."
    fields = [
        url_field("http://192.168.0.x:8123"),
        field("token", "장기 액세스 토큰", secret=True, required=True, full=True),
        verify_field(default=True),
    ]

    def _client(self) -> Client:
        return Client(HomeAssistantCfg(url=self.cfg["url"], token=self.cfg.get("token") or "",
                                       verify_ssl=self.cfg.get("verify_ssl", True)))

    async def status(self) -> dict:
        st = await self._client().status()
        return card(
            summary=" · ".join(p for p in (st.get("location"), f"Core {st['version']}") if p),
            metrics=[metric("Core", st["version"]), metric("엔티티", st["entity_count"]),
                     metric("업데이트 대기", st["update_count"])],
            actions=[act("backup", "백업"),
                     act("restart", "재시작", danger=True, confirm="재시작하는 동안 HA 자동화와 연동이 멈춥니다.")],
        )

    async def action(self, action: str, params: dict):
        if action == "restart":
            await self._client().restart()
            return "재시작을 요청했습니다"
        if action == "backup":
            return await self._client().backup()
        return await super().action(action, params)

    async def devices(self) -> list[dict]:
        out = await self._client().devices()
        for d in out:
            d["hub"], d["hub_name"] = self.id, self.name
        return out

    async def command(self, device_id: str, command: str) -> None:
        await self._client().command(device_id, command)
