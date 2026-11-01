"""HomeOps — 홈랩 · 스마트홈 통합 관리."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles

import asyncio
from contextlib import asynccontextmanager

from . import VERSION, auth
from .backup import service as backup_service
from .config import Runtime, Settings, load_runtime
from .core import Ctx, ctx
from .db import Database
from .routers import backup as backup_router, connections, registry, settings as settings_router, smarthome
from .store import SettingsStore

STATIC = Path(__file__).with_name("static")


def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    runtime = runtime or load_runtime()
    seed = os.environ.get("HOMEOPS_SEED")
    db = Database(runtime.db_path, Path(seed) if seed else None)
    store = SettingsStore(db, runtime.secret_key)
    if settings is not None:  # 테스트 등에서 직접 넘긴 경우
        store.save(settings)
    settings = store.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(backup_service.scheduler(app, VERSION))  # 매일 자동 백업
        try:
            yield
        finally:
            task.cancel()

    app = FastAPI(title="HomeOps", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.ctx = Ctx(settings=settings, runtime=runtime, db=db, store=store)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        else:
            # 화면 파일은 매번 새 버전인지 확인 (업데이트 후 예전 화면이 남지 않도록)
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    app.include_router(auth.router)
    app.include_router(connections.router)
    app.include_router(registry.router)
    app.include_router(smarthome.router)
    app.include_router(settings_router.router)
    app.include_router(backup_router.router)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": VERSION}

    @app.get("/api/audit", dependencies=[Depends(auth.require_user)])
    def audit(request: Request, limit: int = 100) -> list[dict]:
        return ctx(request).db.audit_list(min(max(limit, 1), 500))

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


def get_app() -> FastAPI:  # uvicorn --factory 용
    return create_app()
