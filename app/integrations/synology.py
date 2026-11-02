"""Synology NAS (DSM Web API)."""
from __future__ import annotations

from ..config import SynologyCfg
from ..connectors.synology import Synology as Client
from .base import Integration, act, card, field, metric, row, section, uptime, url_field, verify_field


_PENDING_DEVICE: dict[tuple[str, str], str] = {}


class SynologyNas(Integration):
    type = "synology"
    title = "Synology NAS"
    category = "infra"
    desc = "볼륨 · 디스크 · 리소스 · 재부팅"
    order = 10
    help = ("<b>HomeOps 전용 계정</b>을 권합니다. 재부팅·스토리지 조회에는 관리자 그룹 권한이 필요합니다. "
            "2단계 인증을 켠 계정이면 인증 앱의 6자리 코드를 넣고 저장하세요. HomeOps가 DSM의 "
            "<b>신뢰할 수 있는 기기</b>로 등록되어 이후에는 코드 없이 로그인합니다 "
            "(DSM 개인 설정 → 보안 → 신뢰할 수 있는 기기에서 해제 가능).")
    fields = [
        url_field("https://192.168.0.x:5001"),
        field("username", "아이디", required=True, ph="homeops"),
        field("password", "비밀번호", secret=True, required=True),
        field("otp_code", "2단계 인증 코드 (켠 계정만, 처음 한 번)", ph="6자리 — 저장하면 기기로 등록되고 이후엔 필요 없음"),
        field("device_id", "등록된 기기 ID", kind="hidden", secret=True),
        field("show_disks", "카드에 디스크 목록도 표시", kind="bool", default=False,
              help="꺼 두어도 문제가 있는 디스크는 항상 보여 줍니다"),
        verify_field(default=False),
    ]

    def _client(self, use_otp: bool = False) -> Client:
        return Client(SynologyCfg(url=self.cfg["url"], username=self.cfg.get("username") or "",
                                  password=self.cfg.get("password") or "", verify_ssl=self.cfg.get("verify_ssl", False)),
                      otp_code=(self.cfg.get("otp_code") or "") if use_otp else "",
                      device_id=self.cfg.get("device_id") or "")

    def _key(self) -> tuple[str, str]:
        return (self.cfg.get("url", ""), self.cfg.get("username", ""))

    async def test(self) -> str:
        otp = bool((self.cfg.get("otp_code") or "").strip())
        c = self._client(use_otp=otp)
        n = await c.status()
        msg = f"연결됨 · {n.get('model')} · {n.get('version')}"
        if c.new_device_id:
            # OTP는 한 번만 쓸 수 있으므로, 이어서 저장할 때 쓰도록 받아 둔다
            _PENDING_DEVICE[self._key()] = c.new_device_id
            msg += " · 2단계 인증 확인됨 (저장하면 기기로 등록)"
        return msg

    async def before_save(self) -> dict:
        cfg = dict(self.cfg)
        if (cfg.get("otp_code") or "").strip():
            did = _PENDING_DEVICE.pop(self._key(), None)
            if not did:
                c = self._client(use_otp=True)
                await c.status()
                did = c.new_device_id
            if did:
                cfg["device_id"] = did
        cfg["otp_code"] = ""   # 일회용 코드는 저장하지 않음
        return cfg

    async def status(self) -> dict:
        n = await self._client().status()
        ver = str(n.get("version") or "")
        vol = (n["volumes"] or [{}])[0]
        # 디스크 목록은 설정에서 켰을 때만. 꺼 두어도 정상이 아닌 디스크는 보여 준다
        def bad(d: dict) -> bool:
            return d["status"] not in (None, "normal") or d.get("smart") not in (None, "normal", "safe")
        disks = n["disks"] if self.cfg.get("show_disks") else [d for d in n["disks"] if bad(d)]
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
            ] + ([section("디스크" if self.cfg.get("show_disks") else "문제 있는 디스크",
                          [row(d["name"], f"{d['model']} · {d['temp']}°C" if d.get("temp") else d["model"],
                               badge="정상" if not bad(d) else (d["status"] if d["status"] not in (None, "normal") else f"SMART {d.get('smart')}"),
                               tone="ok" if not bad(d) else "warn") for d in disks])] if disks else []),
            actions=[act("reboot", "재부팅", danger=True, confirm="NAS의 모든 서비스가 잠시 중단됩니다.")],
        )

    async def action(self, action: str, params: dict):
        if action == "reboot":
            await self._client().reboot()
            return "재부팅을 요청했습니다"
        return await super().action(action, params)
