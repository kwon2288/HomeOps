"""일반 설정 (알림 기준 · 백업). 연결은 routers/connections.py 가 다룬다."""
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import ValidationError

from ..auth import require_user
from ..config import SECTION_MODELS, Settings
from ..core import ctx
from ..store import masked, merge_section

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_user)])

LABELS = {"alerts": "알림", "backup": "백업"}
NAMES = {"battery_warn": "배터리 경고 기준", "schedule_time": "자동 백업 시각", "keep_local": "로컬 보관 개수",
         "keep_remote": "원격 보관 개수", "port": "포트", "timezone": "시간대"}


def validation_message(exc: ValidationError) -> str:
    first = exc.errors()[0]
    field = str(first["loc"][-1]) if first["loc"] else ""
    if first["type"] == "value_error":
        return str(first.get("ctx", {}).get("error") or first["msg"]).replace("Value error, ", "")
    if first["type"] == "string_pattern_mismatch" and field == "schedule_time":
        return "자동 백업 시각은 HH:MM 형식으로 입력하세요"
    label = NAMES.get(field, field)
    if first["type"] == "missing":
        return f"{label}을(를) 입력하세요"
    return f"{label}: {first['msg']}"


@router.get("")
def get_settings(request: Request) -> dict:
    return masked(ctx(request).settings)


@router.put("/{section}")
def save_section(section: str, request: Request, data: Any = Body(None)) -> dict:
    if section not in SECTION_MODELS:
        raise HTTPException(404, "알 수 없는 설정")
    if not isinstance(data, dict):
        raise HTTPException(400, "설정 값이 필요합니다")
    c = ctx(request)
    merged = merge_section(section, data, c.settings.model_dump().get(section))
    try:
        value = SECTION_MODELS[section](**merged)
    except ValidationError as exc:
        raise HTTPException(422, validation_message(exc)) from exc
    new = Settings(**{**c.settings.model_dump(), section: value.model_dump()})
    c.store.save(new)
    c.settings = new
    c.db.audit("설정 저장", LABELS[section], "성공")
    return masked(new)
