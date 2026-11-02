"""연결 관리와 공통 상태 · 작업 API. 어떤 연동이든 같은 경로로 다룬다."""
import asyncio
import re
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from .. import integrations
from ..auth import require_user
from ..config import ConnectionCfg, Settings
from ..connectors.base import ConnectorError, describe
from ..core import ctx
from ..integrations.base import Integration
from ..store import masked_conn, merge_conn

router = APIRouter(prefix="/api", tags=["connections"], dependencies=[Depends(require_user)])
STATUS_TIMEOUT = 20


class ActionBody(BaseModel):
    params: dict = {}
    confirm: bool = False


def _cls(type_: str) -> type[Integration]:
    cls = integrations.get(type_)
    if not cls:
        raise HTTPException(400, f"알 수 없는 연동 종류: {type_}")
    return cls


def instance(request: Request, conn: ConnectionCfg | dict) -> Integration:
    data = conn.model_dump() if isinstance(conn, ConnectionCfg) else conn
    return _cls(data["type"])(data, ctx(request))


def _new_id(type_: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", type_.lower()).strip("-") or "conn"
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def _build(request: Request, body: dict, existing: ConnectionCfg | None) -> ConnectionCfg:
    """화면 입력 → 비밀값 병합 → 필드 검증 → 연결."""
    type_ = existing.type if existing else str(body.get("type", ""))
    cls = _cls(type_)
    old = existing.model_dump() if existing else None
    merged = merge_conn({"type": type_, "config": body.get("config") or {}}, old)
    try:
        config = cls.validate(merged["config"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    name = str(body.get("name") or "").strip() or cls.title
    conn_id = existing.id if existing else body.get("id") or ""
    try:
        return ConnectionCfg(id=conn_id or "tmp", type=type_, name=name[:40], config=config)
    except ValidationError as exc:
        raise HTTPException(422, "이름은 40자 이내로 입력하세요") from exc


def _save(request: Request, conns: list[ConnectionCfg]) -> None:
    c = ctx(request)
    new = Settings(**{**c.settings.model_dump(), "connections": [x.model_dump() for x in conns]})
    c.store.save(new)
    c.settings = new


# ---- 연동 종류 · 연결 목록 ----

@router.get("/integrations")
def list_integrations() -> list[dict]:
    return [cls.meta() for cls in integrations.ordered()]


@router.get("/connections")
def list_connections(request: Request) -> list[dict]:
    out = []
    for conn in ctx(request).settings.connections:
        d = masked_conn(conn.model_dump())
        cls = integrations.get(conn.type)
        d["category"] = cls.category_of(conn.config) if cls else "infra"
        d["title"] = cls.title if cls else conn.type
        d["available"] = cls is not None
        out.append(d)
    return out


async def _before_save(request: Request, conn: ConnectionCfg) -> ConnectionCfg:
    try:
        conn.config = await asyncio.wait_for(instance(request, conn).before_save(), STATUS_TIMEOUT)
    except asyncio.TimeoutError as exc:
        raise HTTPException(502, f"{STATUS_TIMEOUT}초 안에 끝나지 않았습니다 (장비가 느리거나 연결되지 않음)") from exc
    except ConnectorError as exc:
        raise HTTPException(400, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, describe(exc)) from exc
    return conn


@router.post("/connections")
async def create_connection(request: Request, body: dict = Body(...)) -> dict:
    c = ctx(request)
    conn = await _before_save(request, _build(request, body, None))
    conn.id = _new_id(conn.type, {x.id for x in c.settings.connections})
    _save(request, [*c.settings.connections, conn])
    c.db.audit("연결 추가", f"{conn.name} ({conn.type})", "성공")
    return masked_conn(conn.model_dump())


@router.put("/connections/{conn_id}")
async def update_connection(conn_id: str, request: Request, body: dict = Body(...)) -> dict:
    c = ctx(request)
    old = c.settings.conn(conn_id)
    if not old:
        raise HTTPException(404, "연결이 없습니다")
    conn = await _before_save(request, _build(request, body, old))
    _save(request, [conn if x.id == conn_id else x for x in c.settings.connections])
    c.db.audit("연결 수정", f"{conn.name} ({conn.type})", "성공")
    return masked_conn(conn.model_dump())


@router.delete("/connections/{conn_id}")
def delete_connection(conn_id: str, request: Request) -> dict:
    c = ctx(request)
    old = c.settings.conn(conn_id)
    if not old:
        raise HTTPException(404, "연결이 없습니다")
    _save(request, [x for x in c.settings.connections if x.id != conn_id])
    c.db.audit("연결 삭제", f"{old.name} ({old.type})", "성공")
    return {"ok": True}


@router.post("/connections/test")
async def test_connection(request: Request, body: dict = Body(...)) -> dict:
    """저장하지 않고 입력값으로 연결만 시험한다. 기존 연결을 고치는 중이면 id 를 함께 보낸다."""
    c = ctx(request)
    existing = c.settings.conn(str(body.get("id") or "")) if body.get("id") else None
    conn = _build(request, body, existing)
    try:
        return {"ok": True, "message": await asyncio.wait_for(instance(request, conn).test(), STATUS_TIMEOUT)}
    except asyncio.TimeoutError:
        return {"ok": False, "message": f"{STATUS_TIMEOUT}초 안에 끝나지 않았습니다 (장비가 느리거나 연결되지 않음)"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": describe(exc)}


# ---- 상태 · 작업 ----

async def _status_one(request: Request, conn: ConnectionCfg) -> dict:
    cls = integrations.get(conn.type)
    base = {"id": conn.id, "type": conn.type, "name": conn.name, "title": cls.title if cls else conn.type,
            "link": conn.config.get("url") or None}
    if not cls:
        return {**base, "online": False, "error": "이 버전에서 지원하지 않는 연동입니다", "card": None}
    try:
        crd = await asyncio.wait_for(instance(request, conn).status(), STATUS_TIMEOUT)
        return {**base, "online": crd.get("online", True), "error": None, "card": crd}
    except asyncio.TimeoutError:
        return {**base, "online": False, "error": f"{STATUS_TIMEOUT}초 안에 끝나지 않았습니다 (장비가 느리거나 연결되지 않음)", "card": None}
    except Exception as exc:  # noqa: BLE001 - 한 시스템이 죽어도 화면은 뜨게
        return {**base, "online": False, "error": describe(exc), "card": None}


def conns_in(request: Request, category: str | None) -> list[ConnectionCfg]:
    out = []
    for conn in ctx(request).settings.connections:
        cls = integrations.get(conn.type)
        cat = cls.category_of(conn.config) if cls else "infra"
        if category in (None, cat):
            out.append(conn)
    return out


async def statuses(request: Request, category: str | None = None) -> list[dict]:
    return list(await asyncio.gather(*(_status_one(request, x) for x in conns_in(request, category))))


@router.get("/status")
async def status(request: Request, category: str | None = None) -> list[dict]:
    if category not in (None, "infra", "smarthome"):
        raise HTTPException(400, "category 는 infra 또는 smarthome")
    return await statuses(request, category)


@router.get("/status/{conn_id}")
async def status_one(conn_id: str, request: Request) -> dict:
    """연결 하나의 상태. 화면은 카드마다 따로 불러서, 느린 시스템이 있어도 나머지는 바로 보인다."""
    conn = ctx(request).settings.conn(conn_id)
    if not conn:
        raise HTTPException(404, "연결이 없습니다")
    return await _status_one(request, conn)


# ---- 대시보드 배치 (화면별 카드 순서 · 크기 · 표시 줄 수 · 숨김) ----

LAYOUT_PAGES = ("infra", "hubs", "manual")   # manual = 스마트홈 허브 화면의 수동 등록 기기


class CardLayout(BaseModel):
    size: Literal["m", "l"] = "m"          # m = 1칸, l = 2칸
    rows: Literal[0, 3, 5, 10, -1] = 5     # 목록 줄 수 (0 = 요약만, -1 = 전부)
    hidden: bool = False


class Layout(BaseModel):
    height: Literal["s", "m", "l", "auto"] = "m"   # 카드 높이: 모두 같은 크기(작게 · 보통 · 크게) 또는 내용에 맞춤
    order: list[str] = Field(default_factory=list, max_length=300)
    cards: dict[str, CardLayout] = Field(default_factory=dict, max_length=300)


def _layout_key(page: str) -> str:
    if page not in LAYOUT_PAGES:
        raise HTTPException(404, "없는 화면입니다")
    return f"layout:{page}"


@router.get("/layout/{page}")
def get_layout(page: str, request: Request) -> dict:
    raw = ctx(request).db.kv_get(_layout_key(page))
    try:
        return Layout.model_validate_json(raw).model_dump() if raw else Layout().model_dump()
    except ValidationError:
        return Layout().model_dump()


@router.put("/layout/{page}")
def put_layout(page: str, body: Layout, request: Request) -> dict:
    ctx(request).db.kv_set(_layout_key(page), body.model_dump_json())
    return body.model_dump()


@router.post("/connections/{conn_id}/actions/{action}")
async def run_action(conn_id: str, action: str, request: Request, body: ActionBody | None = None) -> dict:
    body = body or ActionBody()
    c = ctx(request)
    conn = c.settings.conn(conn_id)
    if not conn:
        raise HTTPException(404, "연결이 없습니다")
    inst = instance(request, conn)
    if not re.match(r"^[a-z][a-z0-9-]{0,30}$", action):
        raise HTTPException(400, "잘못된 작업")
    if inst.confirm_required(action) and not body.confirm:
        raise HTTPException(400, "확인(confirm: true)이 필요한 작업입니다")
    target = conn.name + (f" / {next(iter(body.params.values()))}" if body.params else "")
    try:
        result: Any = await inst.action(action, body.params)
    except ConnectorError as exc:
        c.db.audit(f"{action}", target, f"실패: {exc}")
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        msg = describe(exc)
        c.db.audit(f"{action}", target, f"실패: {msg}")
        raise HTTPException(502, msg) from exc
    c.db.audit(f"{action}", target, "성공")
    if isinstance(result, dict):
        return {"ok": True, **result}
    return {"ok": True, "message": result or "완료했습니다"}


# ---- Hubitat 허브 백업 파일 ----

@router.get("/hub-backups")
def hub_backups(request: Request) -> list[dict]:
    d = ctx(request).runtime.backup_dir
    if not d.exists():
        return []
    files = sorted(d.glob("*.lzf"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"file": p.name, "size": p.stat().st_size, "mtime": int(p.stat().st_mtime)} for p in files]


def _hub_backup_path(request: Request, name: str):
    if not re.match(r"^[\w\-]+\.lzf$", name):
        raise HTTPException(400, "잘못된 파일 이름")
    path = ctx(request).runtime.backup_dir / name
    if not path.is_file():
        raise HTTPException(404, "파일이 없습니다")
    return path


@router.get("/hub-backups/{name}")
def hub_backup_download(name: str, request: Request) -> FileResponse:
    return FileResponse(_hub_backup_path(request, name), filename=name, media_type="application/octet-stream")


@router.delete("/hub-backups/{name}")
def hub_backup_delete(name: str, request: Request) -> dict:
    _hub_backup_path(request, name).unlink()
    ctx(request).db.audit("Hubitat 백업 파일 삭제", name, "성공")
    return {"ok": True}
