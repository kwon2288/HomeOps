"""앱 공용 객체(설정·DB)와 공통 헬퍼."""
from __future__ import annotations

import asyncio
import ipaddress
import re
import shutil
from dataclasses import dataclass
from typing import Any, Awaitable

from fastapi import HTTPException, Request
from pydantic import BaseModel

from .config import Runtime, Settings
from .connectors.base import ConnectorError, describe
from .db import Database
from .store import SettingsStore


@dataclass
class Ctx:
    settings: Settings  # 연결 설정 화면에서 저장하면 통째로 바뀐다
    runtime: Runtime
    db: Database
    store: SettingsStore


def ctx(request: Request) -> Ctx:
    return request.app.state.ctx


class Confirm(BaseModel):
    confirm: bool = False


def require_confirm(body: Confirm | None) -> None:
    if not body or not body.confirm:
        raise HTTPException(400, "확인(confirm: true)이 필요한 작업입니다")


async def guarded(coro: Awaitable[Any]) -> dict[str, Any]:
    """상태 조회 결과를 {online, error, data} 로 감싼다. 한 시스템이 죽어도 화면은 뜨게."""
    try:
        data = await coro
        return {"configured": True, "online": True, "error": None, "data": data}
    except Exception as exc:  # noqa: BLE001 - 어떤 실패든 화면에 표시
        return {"configured": True, "online": False, "error": describe(exc), "data": None}


NOT_CONFIGURED = {"configured": False, "online": False, "error": None, "data": None}


async def run_action(c: Ctx, action: str, target: str, coro: Awaitable[Any]) -> dict[str, Any]:
    """제어 작업 실행 + 작업 기록."""
    try:
        result = await coro
        c.db.audit(action, target, "성공")
        return {"ok": True, "result": result}
    except ConnectorError as exc:
        c.db.audit(action, target, f"실패: {exc}")
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        msg = describe(exc)
        c.db.audit(action, target, f"실패: {msg}")
        raise HTTPException(502, msg) from exc


HOSTNAME = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)*$")


def valid_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return bool(HOSTNAME.match(host))


async def ping(host: str) -> bool:
    """ICMP ping 1회. ping 명령이 없으면 80/443 포트 연결로 대신한다."""
    if not valid_host(host):
        return False
    if shutil.which("ping"):
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", "1", host,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            code = await asyncio.wait_for(proc.wait(), 3)
        except asyncio.TimeoutError:
            proc.kill()
            return False
        if code in (0, 1):  # 0 응답, 1 응답 없음
            return code == 0
        # 그 밖의 코드는 ping 자체 오류(권한 등) → 아래 포트 연결로 확인
    for port in (80, 443):
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 1.5)
            writer.close()
            return True
        except (OSError, asyncio.TimeoutError):
            continue
    return False
