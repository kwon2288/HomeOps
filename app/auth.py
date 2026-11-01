"""관리자 로그인 (서명된 세션 쿠키) · 첫 실행 계정 만들기 · 비밀번호 변경."""
from __future__ import annotations

import hmac
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field

from .core import Ctx, ctx

COOKIE = "homeops_session"
MAX_AGE = 7 * 24 * 3600
MAX_FAILS = 5
LOCK_SECONDS = 300

_fails: dict[str, list[float]] = defaultdict(list)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


class SetupBody(BaseModel):
    username: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_.\-]+$")
    password: str = Field(min_length=8, max_length=200)


class PasswordBody(BaseModel):
    current: str
    new: str = Field(min_length=8, max_length=200)


def env_admin(c: Ctx) -> bool:
    return bool(c.runtime.admin_password)


def needs_setup(c: Ctx) -> bool:
    return not env_admin(c) and c.store.admin() is None


def _serializer(request: Request) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(ctx(request).runtime.secret_key, salt="homeops-session")


def require_user(request: Request) -> str:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        data = _serializer(request).loads(token, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired) as exc:
        raise HTTPException(401, "로그인이 만료되었습니다") from exc
    return data["u"]


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def _check(c: Ctx, username: str, password: str) -> bool:
    if env_admin(c):
        user = c.runtime.admin_user or "admin"
        return hmac.compare_digest(username.encode(), user.encode()) and hmac.compare_digest(
            password.encode(), (c.runtime.admin_password or "").encode())
    return c.store.check_admin(username, password)


def _issue(request: Request, response: Response, username: str) -> None:
    secure = ctx(request).runtime.cookie_secure
    if secure is None:
        secure = request.url.scheme == "https"
    response.set_cookie(
        COOKIE, _serializer(request).dumps({"u": username}),
        max_age=MAX_AGE, httponly=True, samesite="strict", secure=secure,
    )


def _throttle(request: Request) -> str:
    ip = _client_ip(request)
    now = time.time()
    _fails[ip] = [t for t in _fails[ip] if now - t < LOCK_SECONDS]
    if len(_fails[ip]) >= MAX_FAILS:
        raise HTTPException(429, "실패가 많아 잠시 잠겼습니다. 5분 뒤에 다시 시도하세요")
    return ip


@router.get("/status")
def status(request: Request) -> dict:
    """로그인 전 화면이 첫 실행 화면을 보여 줄지 결정할 때 쓴다."""
    c = ctx(request)
    return {"needs_setup": needs_setup(c), "env_admin": env_admin(c)}


@router.post("/setup")
def setup(body: SetupBody, request: Request, response: Response) -> dict:
    c = ctx(request)
    if not needs_setup(c):
        raise HTTPException(409, "이미 관리자 계정이 있습니다")
    c.store.set_admin(body.username, body.password)
    c.db.audit("관리자 계정 생성", body.username, "성공")
    _issue(request, response, body.username)
    return {"user": body.username}


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict:
    c = ctx(request)
    if needs_setup(c):
        raise HTTPException(409, "먼저 관리자 계정을 만들어야 합니다")
    ip = _throttle(request)
    if not _check(c, body.username, body.password):
        _fails[ip].append(time.time())
        raise HTTPException(401, "아이디 또는 비밀번호가 맞지 않습니다")
    _fails.pop(ip, None)
    _issue(request, response, body.username)
    return {"user": body.username}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/me")
def me(request: Request, user: str = Depends(require_user)) -> dict:
    return {"user": user, "env_admin": env_admin(ctx(request))}


@router.post("/password")
def change_password(body: PasswordBody, request: Request, user: str = Depends(require_user)) -> dict:
    c = ctx(request)
    if env_admin(c):
        raise HTTPException(400, "환경 변수(HOMEOPS_ADMIN_PASSWORD)로 지정한 계정은 웹에서 바꿀 수 없습니다")
    ip = _throttle(request)
    if not c.store.check_admin(user, body.current):
        _fails[ip].append(time.time())
        raise HTTPException(400, "현재 비밀번호가 맞지 않습니다")
    c.store.set_admin(user, body.new)
    c.db.audit("비밀번호 변경", user, "성공")
    return {"ok": True}
