from __future__ import annotations

import httpx


class ConnectorError(Exception):
    """외부 시스템 호출 실패. 메시지는 화면에 그대로 보여 줄 수 있는 수준으로 작성한다."""


def make_client(verify: bool = True, timeout: float = 8.0, **kwargs) -> httpx.AsyncClient:
    return httpx.AsyncClient(verify=verify, timeout=timeout, follow_redirects=True, **kwargs)


def describe(exc: Exception) -> str:
    if isinstance(exc, ConnectorError):
        return str(exc)
    if isinstance(exc, httpx.ConnectTimeout):
        return "연결 시간 초과 — 주소가 맞는지, 장비가 켜져 있는지, HomeOps가 그 네트워크에 닿는지 확인하세요"
    if isinstance(exc, httpx.TimeoutException):
        return "응답 시간 초과 — 연결은 됐지만 응답이 오지 않습니다 (장비가 바쁘거나 재시작 중)"
    if isinstance(exc, httpx.ConnectError):
        return "연결할 수 없음 — 주소와 포트를 확인하세요"
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return f"인증 실패 (HTTP {code})"
        return f"HTTP {code}"
    return type(exc).__name__
