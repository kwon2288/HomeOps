"""수동 등록 기기 · 플랫폼 역할 · 연동 경로 (직접 관리하는 기록).

주의: 동적으로 만든 라우트의 본문 타입을 FastAPI가 읽을 수 있도록 지연 평가(__future__ annotations)를 쓰지 않는다.
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from ..auth import require_user
from ..core import ctx, ping, valid_host

router = APIRouter(prefix="/api/registry", tags=["registry"], dependencies=[Depends(require_user)])


class ManualDevice(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    model: str = Field("", max_length=80)
    platform: str = Field("", max_length=40)
    ip: str = Field("", max_length=253)
    roles: list[str] = Field(default_factory=list, max_length=12)
    memo: str = Field("", max_length=500)
    sort: int = 0

    @field_validator("ip")
    @classmethod
    def _ip(cls, v: str) -> str:
        v = v.strip()
        if v and not valid_host(v):
            raise ValueError("IP 주소 또는 호스트 이름 형식이 아닙니다")
        return v


class Platform(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    use: str = Field("", max_length=40)
    features: str = Field("", max_length=300)
    path: str = Field("", max_length=300)
    sort: int = 0


class IntegrationPath(BaseModel):
    src: str = Field(min_length=1, max_length=40)
    via: str = Field("", max_length=80)
    dst: str = Field(min_length=1, max_length=40)
    check_ref: str = Field("", max_length=60)
    sort: int = 0


def _crud(table: str, model: type[BaseModel], path: str) -> None:
    @router.get(f"/{path}", name=f"list_{table}")
    def _list(request: Request) -> list[dict]:
        return ctx(request).db.list(table)

    @router.post(f"/{path}", name=f"create_{table}")
    def _create(body: model, request: Request) -> dict:  # type: ignore[valid-type]
        return ctx(request).db.create(table, body.model_dump())

    @router.put(f"/{path}/{{row_id}}", name=f"update_{table}")
    def _update(row_id: int, body: model, request: Request) -> dict:  # type: ignore[valid-type]
        row = ctx(request).db.update(table, row_id, body.model_dump())
        if not row:
            raise HTTPException(404, "항목이 없습니다")
        return row

    @router.delete(f"/{path}/{{row_id}}", name=f"delete_{table}")
    def _delete(row_id: int, request: Request) -> dict:
        if not ctx(request).db.delete(table, row_id):
            raise HTTPException(404, "항목이 없습니다")
        return {"ok": True}


_crud("manual_devices", ManualDevice, "devices")
_crud("platforms", Platform, "platforms")
_crud("integration_paths", IntegrationPath, "paths")


@router.get("/devices/ping")
async def ping_all(request: Request) -> dict[str, bool | None]:
    devices = ctx(request).db.list("manual_devices")
    targets = [d for d in devices if d["ip"]]
    results = await asyncio.gather(*(ping(d["ip"]) for d in targets))
    out: dict[str, bool | None] = {str(d["id"]): None for d in devices}
    out.update({str(d["id"]): r for d, r in zip(targets, results)})
    return out
