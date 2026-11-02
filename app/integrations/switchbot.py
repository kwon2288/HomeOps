"""SwitchBot (Open API v1.1, 클라우드)."""
from __future__ import annotations

from typing import Any

from ..connectors.base import ConnectorError
from ..connectors.switchbot import DAILY_LIMIT, SwitchBot as Client, has_status, kind_of
from .base import Integration, act, card, field, metric, row, section


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def describe_state(kind: str, s: dict[str, Any]) -> tuple[str | None, str, bool | None]:
    """(화면에 보일 상태, 색, 켜짐 여부)"""
    if "_error" in s:
        return s["_error"], "warn", None
    if kind == "switch":
        on = str(s.get("power", "")).lower() == "on"
        return ("켜짐" if on else "꺼짐"), ("ok" if on else ""), on
    if kind == "curtain":
        pos = _num(s.get("slidePosition"))
        if pos is None:
            return None, "", None
        # 커튼은 0 = 완전히 열림, 100 = 완전히 닫힘
        return ("열림" if pos <= 5 else "닫힘" if pos >= 95 else f"{100 - round(pos)}% 열림"), "", pos < 95
    if kind == "lock":
        st = str(s.get("lockState", "")).lower()
        label = {"locked": "잠김", "unlocked": "열림", "jammed": "걸림"}.get(st, st or None)
        return label, ("ok" if st == "locked" else "warn" if st in ("unlocked", "jammed") else ""), None
    if kind == "meter":
        parts = []
        if s.get("temperature") is not None:
            parts.append(f"{s['temperature']}°")
        if s.get("humidity") is not None:
            parts.append(f"{s['humidity']}%")
        if s.get("CO2") is not None:
            parts.append(f"CO₂ {s['CO2']}")
        return (" · ".join(parts) or None), "", None
    if kind == "contact":
        st = str(s.get("openState", "")).lower()
        if st in ("open", "timeoutnotclose"):
            return ("열림" if st == "open" else "오래 열림"), "warn", None
        return ("닫힘" if st == "close" else st or None), "ok" if st == "close" else "", None
    if kind == "motion":
        moved = s.get("moveDetected")
        return (None if moved is None else "감지" if moved else "없음"), "", None
    if kind == "leak":
        wet = s.get("status")
        return ("누수!" if wet == 1 else "정상"), ("warn" if wet == 1 else "ok"), None
    return None, "", None


class SwitchBotCloud(Integration):
    type = "switchbot"
    title = "SwitchBot"
    category = "smarthome"
    desc = "기기 상태 · 켜기/끄기 · 커튼 · 도어락 · 장면 실행 (클라우드 API)"
    order = 40
    provides_devices = True
    help = ("SwitchBot 앱 → 프로필 → 환경설정 → 정보 → <b>앱 버전을 10번</b> 누르면 나오는 개발자 옵션에서 "
            "<b>토큰</b>과 <b>시크릿</b>을 받으세요. 블루투스 기기(Bot · 커튼 · 도어락 등)는 허브(Hub 2 등)에 연결되어 있고 "
            "앱에서 클라우드 서비스가 켜져 있어야 보입니다. 하루 호출 한도가 10,000회라 상태는 아래 간격만큼 기억해 두고 씁니다.")
    fields = [
        field("token", "토큰", secret=True, required=True, full=True),
        field("secret", "시크릿", secret=True, required=True, full=True),
        field("status_minutes", "상태 새로 받는 간격", kind="select", default="5",
              options=[("1", "1분 (기기 적을 때)"), ("5", "5분 (권장)"), ("15", "15분"), ("60", "1시간")],
              help="기기 20개를 1분 간격으로 보면 하루 최대 약 28,800회라 한도를 넘을 수 있습니다"),
    ]

    def _client(self) -> Client:
        return Client(self.cfg.get("token") or "", self.cfg.get("secret") or "",
                      status_ttl=int(self.cfg.get("status_minutes") or 5) * 60)

    def confirm_required(self, action: str) -> bool:
        return action in {"unlock"} or super().confirm_required(action)

    async def _load(self, force: bool = False) -> tuple[Client, dict, dict, list]:
        c = self._client()
        lists = await c.devices(force=force)
        sts = await c.statuses(lists["devices"])
        try:
            scenes = await c.scenes(force=force)
        except ConnectorError:
            scenes = []
        return c, lists, sts, scenes

    async def test(self) -> str:
        _, lists, sts, scenes = await self._load(force=True)
        devs = lists["devices"]
        hidden = sum(1 for d in devs if d.get("enableCloudService") is False)
        msg = f"연결됨 · 기기 {len(devs)}개 · IR 리모컨 {len(lists['remotes'])}개 · 장면 {len(scenes)}개"
        if hidden:
            msg += f" · 클라우드 서비스가 꺼진 기기 {hidden}개 (앱에서 켜야 상태가 보임)"
        return msg

    async def status(self) -> dict:
        c, lists, sts, scenes = await self._load()
        warn = 20
        if self.ctx is not None and getattr(self.ctx, "settings", None) is not None:
            warn = self.ctx.settings.alerts.battery_warn
        rows, offline, low = [], 0, []
        names = {d["deviceId"]: d.get("deviceName") for d in lists["devices"]}
        for d in lists["devices"]:
            kind = kind_of(d.get("deviceType"))
            s = sts.get(d["deviceId"], {})
            label, tone, on = describe_state(kind, s) if has_status(d) else ("클라우드 꺼짐" if d.get("enableCloudService") is False else None, "", None)
            if "_error" in s:
                offline += 1
            bat = _num(s.get("battery"))
            if bat is not None and bat < warn:
                low.append(f"{d.get('deviceName')} {round(bat)}%")
            note = [d.get("deviceType") or ""]
            if bat is not None:
                note.append(f"배터리 {round(bat)}%")
            if d.get("hubDeviceId") and d["hubDeviceId"] != d["deviceId"] and names.get(d["hubDeviceId"]):
                note.append(f"허브 {names[d['hubDeviceId']]}")
            p = {"id": d["deviceId"]}
            actions = []
            if kind == "switch":
                actions = [act("press", "누르기", params=p)] if d.get("deviceType") == "Bot" else []
                actions += [act("turn-on", "켜기", params=p), act("turn-off", "끄기", params=p)]
            elif kind == "curtain":
                actions = [act("open", "열기", params=p), act("close", "닫기", params=p)]
            elif kind == "lock":
                actions = [act("lock", "잠금", params=p),
                           act("unlock", "열기", danger=True, params=p, confirm=f"{d.get('deviceName')} 도어락을 엽니다.")]
            rows.append(row(d.get("deviceName") or d["deviceId"], " · ".join(x for x in note if x),
                            badge=label, tone=tone, actions=actions))
        # 문제 있는 것(오류 · 열린 문 · 배터리 부족) 먼저, 나머지는 이름순
        rows.sort(key=lambda r: (r["tone"] != "warn", r["name"].lower()))
        remotes = [row(r.get("deviceName") or r["deviceId"], r.get("remoteType") or "IR 리모컨",
                       actions=[act("turn-on", "켜기", params={"id": r["deviceId"]}),
                                act("turn-off", "끄기", params={"id": r["deviceId"]})]) for r in lists["remotes"]]
        scene_rows = [row(s.get("sceneName") or s["sceneId"], actions=[act("scene", "실행", params={"scene": s["sceneId"]})])
                      for s in scenes]
        calls = c.calls_today()
        return card(
            summary=f"기기 {len(lists['devices'])}개 · IR 리모컨 {len(lists['remotes'])}개 · 장면 {len(scenes)}개",
            metrics=[metric("기기", len(lists["devices"])), metric("응답 없음", offline),
                     metric("배터리 부족", len(low)),
                     metric("오늘 API 호출", f"{calls:,}", round(calls / DAILY_LIMIT * 100, 1))],
            note=f"배터리 {warn}% 미만: " + ", ".join(low) if low else "",
            sections=[section("기기 (문제 있는 것 먼저)", rows, empty="기기가 없습니다")]
            + ([section("IR 리모컨", remotes)] if remotes else [])
            + ([section("장면", scene_rows)] if scene_rows else []),
        )

    async def action(self, action: str, params: dict):
        c = self._client()
        if action == "scene":
            await c.run_scene(str(params.get("scene", "")))
            return "장면을 실행했습니다"
        cmd = {"turn-on": "turnOn", "turn-off": "turnOff", "press": "press", "open": "turnOn", "close": "turnOff",
               "lock": "lock", "unlock": "unlock"}.get(action)
        if not cmd:
            return await super().action(action, params)
        await c.command(str(params.get("id", "")), cmd)
        return "명령을 보냈습니다"

    # ---- 스마트홈 연동 화면 (기기 목록 · 켜기/끄기) ----

    async def devices(self) -> list[dict]:
        _, lists, sts, _ = await self._load()
        out = []
        for d in lists["devices"]:
            kind = kind_of(d.get("deviceType"))
            s = sts.get(d["deviceId"], {})
            label, tone, on = describe_state(kind, s) if has_status(d) else (None, "", None)
            bat = _num(s.get("battery"))
            detail = [d.get("deviceType") or "SwitchBot"]
            if bat is not None:
                detail.append(f"배터리 {round(bat)}%")
            out.append({
                "source": "SB", "hub": self.id, "hub_name": self.name, "id": d["deviceId"],
                "label": d.get("deviceName") or d["deviceId"],
                "room": d.get("roomName") or "SwitchBot",
                "is_switch": kind == "switch" and "_error" not in s and bool(s),
                "on": bool(on), "state_label": label, "tone": tone or "plain",
                "detail": " · ".join(detail), "battery": int(bat) if bat is not None else None,
                "contact_open": kind == "contact" and tone == "warn",
            })
        return out

    async def command(self, device_id: str, command: str) -> None:
        await self._client().command(device_id, {"on": "turnOn", "off": "turnOff"}[command])
