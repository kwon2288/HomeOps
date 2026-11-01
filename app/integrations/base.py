"""연동(Integration) 플러그인의 기반.

새 시스템을 붙이려면 이 폴더에 파일 하나를 만들고 `Integration`을 상속한 클래스를 두면 된다.
화면(연결 추가 목록, 입력 폼, 상태 카드, 작업 버튼)은 클래스 선언을 보고 자동으로 만들어진다.

    class MyThing(Integration):
        type = "mything"                 # 저장용 고유 이름 (영문 소문자)
        title = "My Thing"               # 화면 이름
        category = "infra"               # infra | smarthome
        desc = "한 줄 설명"
        help = "토큰 만드는 곳 등 안내 (HTML 가능)"
        fields = [field("url", "주소", kind="url", required=True), field("token", "토큰", secret=True)]

        async def status(self) -> dict: ...          # 상태 카드 (card() 로 만들기)
        async def action(self, action, params): ...  # 작업 버튼 처리
"""
from __future__ import annotations

import re
from typing import Any, ClassVar

from ..connectors.base import ConnectorError

# ---- 입력 칸 ----


def field(name: str, label: str, *, kind: str = "text", secret: bool = False, required: bool = False,
          ph: str = "", default: Any = None, full: bool = False, help: str = "",
          options: list[tuple[str, str]] | None = None) -> dict:
    """kind: text | url | number | bool | select (options=[(값, 표시 이름)]). secret=True 면 암호화 저장·화면에 가림."""
    return {"name": name, "label": label, "kind": kind, "secret": secret, "required": required, "ph": ph,
            "default": default, "full": full, "help": help, "options": [list(o) for o in (options or [])]}


def url_field(ph: str) -> dict:
    return field("url", "주소", kind="url", required=True, ph=ph, full=True)


def verify_field(default: bool = False) -> dict:
    label = "HTTPS 인증서 검증" + ("" if default else " (자체 서명 인증서면 끄기)")
    return field("verify_ssl", label, kind="bool", default=default, full=True)


# ---- 상태 카드 ----


def metric(label: str, value: Any, pct: float | None = None, unit: str = "") -> dict:
    v = "—" if value is None or value == "" else f"{value}{unit}"
    return {"label": label, "value": v, "pct": pct}


def act(id: str, label: str, *, danger: bool = False, confirm: str | None = None, params: dict | None = None) -> dict:
    """작업 버튼. confirm 에 문장을 주면 화면에서 확인 창을 띄우고, 서버도 확인을 요구한다."""
    return {"id": id, "label": label, "danger": danger, "confirm": confirm, "params": params or {}}


def row(name: str, note: str = "", *, badge: str | None = None, tone: str = "", actions: list[dict] | None = None) -> dict:
    return {"name": name, "note": note, "badge": badge, "tone": tone, "actions": actions or []}


def section(title: str, rows: list[dict], empty: str = "") -> dict:
    return {"title": title, "rows": rows, "empty": empty}


def card(summary: str = "", metrics: list[dict] | None = None, sections: list[dict] | None = None,
         actions: list[dict] | None = None, online: bool = True, note: str = "") -> dict:
    return {"online": online, "summary": summary, "metrics": metrics or [], "sections": sections or [],
            "actions": actions or [], "note": note}


def pct(part: Any, whole: Any) -> float | None:
    try:
        part, whole = float(part or 0), float(whole or 0)
    except (TypeError, ValueError):
        return None
    return round(part / whole * 100, 1) if whole else None


def uptime(sec: Any) -> str | None:
    try:
        sec = int(float(sec))
    except (TypeError, ValueError):
        return None
    d, h, m = sec // 86400, sec % 86400 // 3600, sec % 3600 // 60
    return f"{d}일 {h}시간" if d else f"{h}시간 {m}분"


# ---- 기반 클래스 ----


class Integration:
    type: ClassVar[str] = ""
    title: ClassVar[str] = ""
    category: ClassVar[str] = "infra"   # infra | smarthome
    desc: ClassVar[str] = ""
    help: ClassVar[str] = ""
    order: ClassVar[int] = 100
    fields: ClassVar[list[dict]] = []
    provides_devices: ClassVar[bool] = False   # 스마트홈 연동 화면의 기기 목록·제어 제공 여부

    def __init__(self, conn: dict, ctx: Any = None):
        self.conn = conn
        self.id: str = conn["id"]
        self.name: str = conn.get("name") or self.title
        self.cfg: dict = conn.get("config") or {}
        self.ctx = ctx

    # -- 화면용 메타데이터 --
    @classmethod
    def meta(cls) -> dict:
        return {"type": cls.type, "title": cls.title, "category": cls.category, "desc": cls.desc,
                "help": cls.help, "fields": cls.fields, "devices": cls.provides_devices}

    @classmethod
    def category_of(cls, config: dict) -> str:
        """이 연결을 어느 메뉴에 보여 줄지 (보통은 category 고정)."""
        return cls.category

    @classmethod
    def secret_fields(cls) -> list[str]:
        return [f["name"] for f in cls.fields if f["secret"]]

    @classmethod
    def validate(cls, config: dict) -> dict:
        """입력값을 필드 선언에 맞춰 정리한다. 잘못되면 ValueError(화면에 보일 문장)."""
        out: dict = {}
        for f in cls.fields:
            v = config.get(f["name"], f["default"])
            if f["kind"] == "bool":
                out[f["name"]] = bool(v) if v is not None else bool(f["default"])
                continue
            if f["kind"] == "number":
                if v in (None, ""):
                    v = f["default"]
                if v in (None, ""):
                    if f["required"]:
                        raise ValueError(f"{f['label']}을(를) 입력하세요")
                    out[f["name"]] = None
                    continue
                try:
                    out[f["name"]] = int(v)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{f['label']}은(는) 숫자로 입력하세요") from exc
                continue
            v = "" if v is None else str(v).strip()
            if f["required"] and not v:
                raise ValueError(f"{f['label']}을(를) 입력하세요")
            if f["kind"] == "select" and f["options"] and v not in [o[0] for o in f["options"]]:
                v = f["default"] if f["default"] is not None else f["options"][0][0]
            if f["kind"] == "url" and v:
                if not re.match(r"^https?://[^\s/]+", v):
                    raise ValueError(f"{f['label']}는 http:// 또는 https:// 로 시작해야 합니다")
                v = v.rstrip("/")
            out[f["name"]] = v
        return out

    # -- 동작 (필요한 것만 구현) --
    async def status(self) -> dict:
        raise NotImplementedError

    async def test(self) -> str:
        c = await self.status()
        return "연결됨" + (f" · {c['summary']}" if c.get("summary") else "")

    async def action(self, action: str, params: dict) -> Any:
        raise ConnectorError("지원하지 않는 작업입니다")

    def confirm_required(self, action: str) -> bool:
        """서버 쪽에서도 확인을 요구할 위험 작업."""
        return action in {"reboot", "restart", "shutdown", "stop", "power-off", "reset"}

    async def devices(self) -> list[dict]:
        return []

    async def command(self, device_id: str, command: str) -> None:
        raise ConnectorError("기기 제어를 지원하지 않습니다")

    async def mode_hsm(self) -> dict:
        return {}
