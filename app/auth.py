"""단일 관리자 로그인 (서명된 세션 쿠키) + 로그인 실패 잠금."""
from __future__ import annotations

import hmac
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel

from .core import ctx

COOKIE = "homeops_session"
MAX_AGE = 7 * 24 * 3600
MAX_FAILS = 5
LOCK_SECONDS = 300

_fails: dict[str, list[float]] = defaultdict(list)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


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


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict:
    ip = _client_ip(request)
    now = time.time()
    _fails[ip] = [t for t in _fails[ip] if now - t < LOCK_SECONDS]
    if len(_fails[ip]) >= MAX_FAILS:
        raise HTTPException(429, "로그인 실패가 많아 잠시 잠겼습니다. 5분 뒤에 다시 시도하세요")
    rt = ctx(request).runtime
    ok_user = hmac.compare_digest(body.username.encode(), rt.admin_user.encode())
    ok_pass = hmac.compare_digest(body.password.encode(), rt.admin_password.encode())
    if not (ok_user and ok_pass):
        _fails[ip].append(now)
        raise HTTPException(401, "아이디 또는 비밀번호가 맞지 않습니다")
    _fails.pop(ip, None)
    token = _serializer(request).dumps({"u": rt.admin_user})
    response.set_cookie(
        COOKIE, token, max_age=MAX_AGE, httponly=True, samesite="strict", secure=rt.cookie_secure,
    )
    return {"user": rt.admin_user}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/me")
def me(user: str = Depends(require_user)) -> dict:
    return {"user": user}
