"""연결 설정: 웹 화면에서 각 시스템의 주소·토큰을 입력하고 연결을 시험한다."""
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import TypeAdapter, ValidationError

from ..auth import require_user
from ..config import SECTION_MODELS, HubitatCfg, Settings
from ..connectors.base import describe
from ..connectors.homeassistant import HomeAssistant
from ..connectors.homebridge import Homebridge
from ..connectors.hubitat import Hubitat
from ..connectors.portainer import Portainer
from ..connectors.proxmox import Proxmox
from ..connectors.synology import Synology
from ..core import ctx
from ..store import masked, merge_section

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_user)])

SECTIONS = {"hubitat", *SECTION_MODELS}
HUBS = TypeAdapter(list[HubitatCfg])
LABELS = {
    "hubitat": "Hubitat", "home_assistant": "Home Assistant", "homebridge": "Homebridge",
    "synology": "Synology NAS", "proxmox": "Proxmox VE", "portainer": "Portainer", "alerts": "알림",
}


def _validation_message(exc: ValidationError) -> str:
    first = exc.errors()[0]
    field = str(first["loc"][-1]) if first["loc"] else ""
    names = {"url": "주소", "id": "허브 ID", "name": "이름", "app_id": "Maker API App ID", "username": "아이디",
             "token_id": "토큰 ID", "battery_warn": "배터리 경고 기준"}
    label = names.get(field, field)
    if first["type"] == "string_pattern_mismatch":
        if field == "url":
            return "주소는 http:// 또는 https:// 로 시작해야 합니다"
        if field == "id":
            return "허브 ID는 영문 소문자·숫자·-·_ 로만 입력하세요 (예: main)"
    if first["type"] == "missing":
        return f"{label}을(를) 입력하세요"
    if first["type"] in ("string_too_short",):
        return f"{label}을(를) 입력하세요"
    return f"{label}: {first['msg']}"


def _build(section: str, data: Any, request: Request) -> Any:
    """화면 입력 → 기존 비밀값 병합 → 검증된 모델."""
    c = ctx(request)
    old = c.settings.model_dump().get(section)
    try:
        if section == "hubitat":
            if not isinstance(data, list):
                raise HTTPException(400, "허브 목록이 필요합니다")
            merged = merge_section(section, data, old)
            hubs = HUBS.validate_python(merged)
            ids = [h.id for h in hubs]
            if len(ids) != len(set(ids)):
                raise HTTPException(400, "허브 ID가 겹칩니다")
            return hubs
        if data is None:
            if section == "alerts":
                raise HTTPException(400, "알림 설정은 지울 수 없습니다")
            return None
        merged = merge_section(section, data, old)
        return SECTION_MODELS[section](**merged)
    except ValidationError as exc:
        raise HTTPException(422, _validation_message(exc)) from exc


@router.get("")
def get_settings(request: Request) -> dict:
    return masked(ctx(request).settings)


@router.put("/{section}")
def save_section(section: str, request: Request, data: Any = Body(None)) -> dict:
    if section not in SECTIONS:
        raise HTTPException(404, "알 수 없는 설정")
    c = ctx(request)
    value = _build(section, data, request)
    if value is None:
        dumped = None
    elif isinstance(value, list):
        dumped = [h.model_dump() for h in value]
    else:
        dumped = value.model_dump()
    new = Settings(**{**c.settings.model_dump(), section: dumped})
    c.store.save(new)
    c.settings = new
    request.app.state.homebridge = None  # 로그인 토큰 캐시 초기화
    c.db.audit("연결 설정 저장", LABELS[section], "삭제" if value is None else "성공")
    return masked(new)


@router.post("/test/{section}")
async def test_section(section: str, request: Request, data: Any = Body(None)) -> dict:
    """저장하지 않고 입력값으로 연결만 시험한다. hubitat은 허브 하나를 보낸다."""
    if section not in SECTIONS or section == "alerts":
        raise HTTPException(404, "알 수 없는 설정")
    try:
        if section == "hubitat":
            cfg = _build("hubitat", [data], request)[0]
            return await _test_hub(cfg)
        cfg = _build(section, data, request)
        if cfg is None:
            raise HTTPException(400, "입력값이 없습니다")
        if section == "home_assistant":
            st = await HomeAssistant(cfg).status()
            return {"ok": True, "message": f"연결됨 · Core {st['version']} · 엔티티 {st['entity_count']}개"}
        if section == "homebridge":
            st = await Homebridge(cfg).status()
            acc = f" · 액세서리 {st['accessory_count']}개" if st["insecure_mode"] else " · 액세서리 목록은 insecure 모드 필요"
            return {"ok": True, "message": f"연결됨 · Homebridge {st['version'] or '?'}{acc}"}
        if section == "synology":
            st = await Synology(cfg).status()
            return {"ok": True, "message": f"연결됨 · {st['model']} · {st['version']}"}
        if section == "proxmox":
            st = await Proxmox(cfg).status()
            return {"ok": True, "message": f"연결됨 · PVE {st['version']} · VM/LXC {len(st['guests'])}개"}
        if section == "portainer":
            st = await Portainer(cfg).status()
            return {"ok": True, "message": f"연결됨 · Portainer {st['version']} · 컨테이너 {len(st['containers'])}개"}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": describe(exc)}
    raise HTTPException(404, "알 수 없는 설정")


async def _test_hub(cfg: HubitatCfg) -> dict:
    h = Hubitat(cfg)
    parts = []
    if cfg.maker_api:
        try:
            devices = await h.devices()
            parts.append(f"Maker API 기기 {len(devices)}개")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"Maker API: {describe(exc)}"}
    st = await h.status()
    if st["free_memory_kb"] is not None or st["temperature_c"] is not None:
        parts.append("허브 관리 정보 확인됨" + (f" · 펌웨어 {st['firmware']}" if st["firmware"] else ""))
    elif not cfg.maker_api:
        return {"ok": False, "message": "허브에 연결하지 못했습니다 (주소 또는 허브 로그인 확인)"}
    else:
        parts.append("메모리·온도 등 관리 정보는 읽지 못함 (허브 로그인 설정 확인)")
    return {"ok": True, "message": "연결됨 · " + " · ".join(parts)}
