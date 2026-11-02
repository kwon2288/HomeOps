"""Homey Pro (로컬 Web API, API 키). Homey에 잡힌 LG ThinQ 등 다른 앱의 기기도 함께 가져온다."""
from __future__ import annotations

from typing import Any

from ..connectors.homey import Homey as Client, app_of, cap, setable
from .base import Integration, act, card, field, metric, row, section, uptime, url_field, verify_field

APP_LABEL = {"com.lgthinq": "LG ThinQ", "com.lge.thinq": "LG ThinQ", "com.lg.thinq": "LG ThinQ"}


def app_label(app: str) -> str:
    if app in APP_LABEL or "thinq" in app.lower():
        return APP_LABEL.get(app, "LG ThinQ")
    return app.split(".")[-1] if app else ""


def state_of(d: dict[str, Any]) -> tuple[str | None, str]:
    """(화면에 보일 상태, 색)"""
    if d.get("available") is False:
        return (d.get("unavailableMessage") or "응답 없음")[:40], "warn"
    caps = d.get("capabilities") or list((d.get("capabilitiesObj") or {}).keys())
    if "onoff" in caps and cap(d, "onoff") is not None:
        on = bool(cap(d, "onoff"))
        return ("켜짐" if on else "꺼짐"), ("ok" if on else "")
    if "locked" in caps and cap(d, "locked") is not None:
        return ("잠김" if cap(d, "locked") else "열림"), ("ok" if cap(d, "locked") else "warn")
    if "alarm_contact" in caps and cap(d, "alarm_contact") is not None:
        return ("열림" if cap(d, "alarm_contact") else "닫힘"), ("warn" if cap(d, "alarm_contact") else "ok")
    if "alarm_water" in caps and cap(d, "alarm_water"):
        return "누수!", "warn"
    if "alarm_motion" in caps and cap(d, "alarm_motion") is not None:
        return ("감지" if cap(d, "alarm_motion") else "없음"), ""
    if "windowcoverings_set" in caps and cap(d, "windowcoverings_set") is not None:
        return f"{round(float(cap(d, 'windowcoverings_set')) * 100)}% 열림", ""
    parts = []
    if cap(d, "measure_temperature") is not None:
        parts.append(f"{cap(d, 'measure_temperature')}°")
    if cap(d, "measure_humidity") is not None:
        parts.append(f"{cap(d, 'measure_humidity')}%")
    if cap(d, "measure_power") is not None:
        parts.append(f"{cap(d, 'measure_power')}W")
    return (" · ".join(parts) or None), ""


class HomeyPro(Integration):
    type = "homey"
    title = "Homey Pro"
    category = "smarthome"
    desc = "기기 상태 · 켜기/끄기 · 플로우 실행 (LG ThinQ 등 Homey 앱 기기 포함, 로컬 API)"
    order = 35
    provides_devices = True
    help = ("Homey 웹 앱(my.homey.app) → 설정 → <b>API Keys</b> → 새 API 키에서 기기 읽기·제어 권한(플로우를 쓸 거면 플로우 권한도)을 "
            "주고 만든 키를 넣으세요. 주소는 Homey Pro의 집 안 IP입니다 (예: <code>http://192.168.0.x</code>). "
            "Homey Pro (Early 2019) 이하는 API 키를 지원하지 않습니다. "
            "Hubitat에도 있는 기기가 겹치지 않게 하려면 <b>가져올 앱</b>에 <code>lg</code>처럼 앱 이름 일부를 넣으세요.")
    fields = [
        url_field("http://192.168.0.x"),
        field("api_key", "API 키", secret=True, required=True, full=True),
        field("app_filter", "가져올 앱 (비우면 전체)", ph="예: lg — 이 글자가 들어간 Homey 앱의 기기만",
              help="쉼표로 여러 개: lg, tuya"),
        field("show_flows", "카드에 플로우 목록도 표시 (실행 버튼)", kind="bool", default=False),
        verify_field(default=False),
    ]

    def _client(self) -> Client:
        return Client(self.cfg["url"], self.cfg.get("api_key") or "", verify_ssl=self.cfg.get("verify_ssl", False))

    def _wanted(self, d: dict[str, Any]) -> bool:
        words = [w.strip().lower() for w in str(self.cfg.get("app_filter") or "").split(",") if w.strip()]
        if not words:
            return True
        hay = f"{app_of(d)} {app_label(app_of(d))}".lower()
        return any(w in hay for w in words)

    async def _load(self) -> dict[str, Any]:
        snap = await self._client().snapshot(with_flows=bool(self.cfg.get("show_flows")))
        snap["all_count"] = len(snap["devices"])
        snap["devices"] = [d for d in snap["devices"] if self._wanted(d)]
        return snap

    async def test(self) -> str:
        snap = await self._load()
        msg = f"연결됨 · 기기 {len(snap['devices'])}개"
        if snap["all_count"] != len(snap["devices"]):
            msg += f" (전체 {snap['all_count']}개 중 '{self.cfg.get('app_filter')}' 앱)"
        apps = sorted({app_label(app_of(d)) for d in snap["devices"]} - {""})
        if apps:
            msg += " · 앱: " + ", ".join(apps[:6])
        if not snap["zones"]:
            msg += " · 구역(방) 이름을 읽을 권한 없음"
        return msg

    async def status(self) -> dict:
        snap = await self._load()
        sysinfo = snap["system"]
        warn = 20
        if self.ctx is not None and getattr(self.ctx, "settings", None) is not None:
            warn = self.ctx.settings.alerts.battery_warn
        rows, offline, low = [], 0, []
        for d in snap["devices"]:
            label, tone = state_of(d)
            if d.get("available") is False:
                offline += 1
            bat = cap(d, "measure_battery")
            if isinstance(bat, (int, float)) and bat < warn:
                low.append(f"{d.get('name')} {round(bat)}%")
                tone = tone or "warn"
            note = [x for x in (snap["zones"].get(d.get("zone")), app_label(app_of(d)), d.get("class")) if x]
            if isinstance(bat, (int, float)):
                note.append(f"배터리 {round(bat)}%")
            actions = []
            if setable(d, "onoff") and d.get("available") is not False:
                p = {"id": d.get("id")}
                actions = [act("turn-on", "켜기", params=p), act("turn-off", "끄기", params=p)]
            rows.append(row(d.get("name") or d.get("id"), " · ".join(note), badge=label, tone=tone, actions=actions))
        rows.sort(key=lambda r: (r["tone"] != "warn", (r["name"] or "").lower()))
        flows = [row(f["name"] or f["id"], "고급 플로우" if f["kind"] == "advancedflow" else "플로우",
                     actions=[act("flow", "실행", params={"id": f["id"], "kind": f["kind"]})])
                 for f in sorted(snap["flows"], key=lambda f: (f["name"] or "").lower())]
        ver = sysinfo.get("homeyVersion") or sysinfo.get("version")
        up = uptime(sysinfo.get("uptime")) if sysinfo.get("uptime") else ""
        mem = None
        if sysinfo.get("totalmem") and sysinfo.get("freemem") is not None:
            mem = round((1 - sysinfo["freemem"] / sysinfo["totalmem"]) * 100, 1)
        filt = str(self.cfg.get("app_filter") or "").strip()
        return card(
            summary=" · ".join(x for x in (f"Homey {ver}" if ver else "Homey Pro", f"가동 {up}" if up else "",
                                           f"'{filt}' 앱 기기만" if filt else "") if x),
            metrics=[metric("기기", len(snap["devices"])), metric("응답 없음", offline),
                     metric("배터리 부족", len(low)), metric("메모리", mem, mem, "%") if mem is not None
                     else metric("플로우", len(snap["flows"])) if self.cfg.get("show_flows") else metric("전체 기기", snap["all_count"])],
            note=f"배터리 {warn}% 미만: " + ", ".join(low) if low else "",
            sections=[section("기기 (문제 있는 것 먼저)", rows, empty="가져온 기기가 없습니다 — 가져올 앱 설정을 확인하세요")]
            + ([section("플로우", flows)] if flows else []),
        )

    async def action(self, action: str, params: dict):
        c = self._client()
        if action in ("turn-on", "turn-off"):
            await c.set_capability(str(params.get("id", "")), "onoff", action == "turn-on")
            return "명령을 보냈습니다"
        if action == "flow":
            await c.trigger_flow(str(params.get("id", "")), str(params.get("kind", "flow")))
            return "플로우를 실행했습니다"
        return await super().action(action, params)

    # ---- 스마트홈 연동 화면 ----

    async def devices(self) -> list[dict]:
        snap = await self._load()
        out = []
        for d in snap["devices"]:
            label, tone = state_of(d)
            bat = cap(d, "measure_battery")
            detail = [x for x in (app_label(app_of(d)), d.get("class")) if x]
            if isinstance(bat, (int, float)):
                detail.append(f"배터리 {round(bat)}%")
            is_switch = setable(d, "onoff") and d.get("available") is not False and cap(d, "onoff") is not None
            out.append({
                "source": "HY", "hub": self.id, "hub_name": self.name, "id": str(d.get("id")),
                "label": d.get("name") or str(d.get("id")),
                "room": snap["zones"].get(d.get("zone")) or "Homey",
                "is_switch": is_switch, "on": bool(cap(d, "onoff")),
                "state_label": label, "tone": tone or "plain",
                "detail": " · ".join(detail) or "Homey",
                "battery": int(bat) if isinstance(bat, (int, float)) else None,
                "contact_open": bool(cap(d, "alarm_contact")),
            })
        return out

    async def command(self, device_id: str, command: str) -> None:
        await self._client().set_capability(device_id, "onoff", command == "on")
