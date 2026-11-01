"""Hubitat Elevation 허브 (Maker API + 허브 관리 URL)."""
from __future__ import annotations

from ..config import HubitatCfg, HubLogin, MakerApi
from ..connectors.base import ConnectorError, describe
from ..connectors.hubitat import Hubitat, normalize_device
from .base import Integration, act, card, field, metric


class HubitatHub(Integration):
    type = "hubitat"
    title = "Hubitat 허브"
    category = "smarthome"
    desc = "기기 제어 · 모드 · 허브 백업 · 재부팅"
    order = 10
    provides_devices = True
    help = ('허브 웹 → Apps → Add Built-In App → <b>Maker API</b>를 설치하고, "Allow Access via Local IP Address"를 켠 뒤 '
            '관리할 기기를 고르세요. 예시 URL의 <code>/apps/api/<b>App ID</b>/…?access_token=<b>토큰</b></code>을 넣으면 됩니다. '
            '메모리·온도·백업·재부팅은 허브 관리 화면의 비공식 URL을 쓰므로 펌웨어에 따라 값이 비어 있을 수 있습니다.')
    fields = [
        field("url", "허브 주소", kind="url", required=True, ph="http://192.168.0.80"),
        field("role", "역할", ph="예: Zigbee 전용"),
        field("app_id", "Maker API App ID", kind="number", ph="예: 12"),
        field("token", "Maker API Access Token", secret=True),
        field("login_user", "허브 로그인 아이디 (로그인 보안을 켠 경우만)", ph="비워 두면 사용 안 함"),
        field("login_password", "허브 로그인 비밀번호", secret=True),
    ]

    def _hcfg(self) -> HubitatCfg:
        c = self.cfg
        return HubitatCfg(
            id=self.id, name=self.name, url=c.get("url") or "http://", role=c.get("role") or "",
            maker_api=MakerApi(app_id=int(c["app_id"]), token=c.get("token") or "") if c.get("app_id") else None,
            login=HubLogin(username=c["login_user"], password=c.get("login_password") or "") if c.get("login_user") else None,
        )

    def _hub(self) -> Hubitat:
        return Hubitat(self._hcfg())

    async def status(self) -> dict:
        st = await self._hub().status()
        if not st["online"]:
            raise ConnectorError("응답 없음 (주소 · Maker API · 허브 로그인 확인)")
        mem = st["free_memory_kb"]
        parts = [p for p in (self.cfg.get("role"), f"펌웨어 {st['firmware']}" if st["firmware"] else "") if p]
        return card(
            summary=" · ".join(parts),
            metrics=[
                metric("기기", st["device_count"]),
                metric("여유 메모리", round(mem / 1024) if mem is not None else None, unit=" MB"),
                metric("내부 온도", st["temperature_c"], unit="°C"),
                metric("DB 크기", st["database_mb"], unit=" MB"),
            ],
            actions=[
                act("backup", "백업"),
                act("reboot", "재부팅", danger=True, confirm="재부팅하는 동안(약 1~2분) 이 허브의 자동화가 멈춥니다."),
            ],
        )

    async def test(self) -> str:
        h = self._hub()
        parts = []
        st = await h.status()   # 허브에 닿는지부터 (안 닿으면 이유를 알려 주고 끝)
        if self.cfg.get("app_id"):
            try:
                devices = await h.device_ids()
                parts.append(f"Maker API 기기 {len(devices)}개")
            except Exception as exc:  # noqa: BLE001
                raise ConnectorError(f"Maker API: {describe(exc)}") from exc
        if st["free_memory_kb"] is not None or st["temperature_c"] is not None:
            parts.append("허브 관리 정보 확인됨" + (f" · 펌웨어 {st['firmware']}" if st["firmware"] else ""))
        elif not self.cfg.get("app_id"):
            raise ConnectorError("허브에 연결하지 못했습니다 (주소 또는 허브 로그인 확인)")
        else:
            parts.append("메모리·온도 등 관리 정보는 읽지 못함 (허브 로그인 설정 확인)")
        return "연결됨 · " + " · ".join(parts)

    async def action(self, action: str, params: dict):
        if action == "reboot":
            await self._hub().reboot()
            return "재부팅을 요청했습니다"
        if action == "backup":
            rt = self.ctx.runtime
            r = await self._hub().backup(rt.backup_dir, rt.backup_keep)
            return f"백업 저장 ({r['size'] / 1048576:.1f} MB)"
        return await super().action(action, params)

    async def devices(self) -> list[dict]:
        if not self.cfg.get("app_id"):
            return []
        cfg = self._hcfg()
        return [normalize_device(cfg, d) for d in await self._hub().devices()]

    async def command(self, device_id: str, command: str) -> None:
        await self._hub().command(device_id, command)

    async def mode_hsm(self) -> dict:
        if not self.cfg.get("app_id"):
            return {}
        return await self._hub().mode_and_hsm()
