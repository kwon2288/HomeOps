"""Synology NAS (DSM Web API)."""
from __future__ import annotations

from ..config import SynologyCfg
from ..connectors.synology import Synology as Client
from .base import Integration, act, card, field, metric, row, section, uptime, url_field, verify_field


class SynologyNas(Integration):
    type = "synology"
    title = "Synology NAS"
    category = "infra"
    desc = "볼륨 · 디스크 · 리소스 · 재부팅"
    order = 10
    help = "2단계 인증을 끈 <b>HomeOps 전용 계정</b>을 만들어 쓰세요. 재부팅·스토리지 조회에는 관리자 그룹 권한이 필요합니다."
    fields = [
        url_field("https://192.168.0.x:5001"),
        field("username", "아이디", required=True, ph="homeops"),
        field("password", "비밀번호", secret=True, required=True),
        verify_field(default=False),
    ]

    def _client(self) -> Client:
        return Client(SynologyCfg(url=self.cfg["url"], username=self.cfg.get("username") or "",
                                  password=self.cfg.get("password") or "", verify_ssl=self.cfg.get("verify_ssl", False)))

    async def status(self) -> dict:
        n = await self._client().status()
        ver = str(n.get("version") or "")
        vol = (n["volumes"] or [{}])[0]
        return card(
            summary=" · ".join(p for p in (n.get("model"), ver if ver.startswith("DSM") else f"DSM {ver}",
                                           f"가동 {uptime(n.get('uptime'))}" if uptime(n.get("uptime")) else "") if p),
            metrics=[
                metric("볼륨 사용률", round(vol["used_pct"]) if vol.get("used_pct") is not None else None, vol.get("used_pct"), "%"),
                metric("CPU", n.get("cpu_pct"), n.get("cpu_pct"), "%"),
                metric("메모리", n.get("mem_pct"), n.get("mem_pct"), "%"),
                metric("디스크 상태", n.get("disk_health")),
            ],
            sections=[
                section("볼륨", [row(v["name"], f"{'정상' if v['status'] == 'normal' else v['status']} · {v['total_tb']}TB",
                                    badge=f"{round(v['used_pct'])}%" if v.get("used_pct") is not None else None,
                                    tone="warn" if (v.get("used_pct") or 0) >= 85 else "") for v in n["volumes"]]),
                section("디스크", [row(d["name"], f"{d['model']} · {d['temp']}°C" if d.get("temp") else d["model"],
                                     badge="정상" if d["status"] == "normal" else (d["status"] or "—"),
                                     tone="ok" if d["status"] == "normal" else "warn") for d in n["disks"]]),
            ],
            actions=[act("reboot", "재부팅", danger=True, confirm="NAS의 모든 서비스가 잠시 중단됩니다.")],
        )

    async def action(self, action: str, params: dict):
        if action == "reboot":
            await self._client().reboot()
            return "재부팅을 요청했습니다"
        return await super().action(action, params)
