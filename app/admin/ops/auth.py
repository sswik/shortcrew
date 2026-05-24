"""패스워드 인증·세션 쿠키. 패스워드는 상수 시간 비교."""
from __future__ import annotations

import hmac
import hashlib
import secrets
from typing import Annotated

from fastapi import Cookie, Depends, Request, Response
from fastapi.responses import RedirectResponse

COOKIE_NAME = "shortcrew-ops_auth"


class AuthRequiredRedirect(Exception):
    """의존성에서 로그인 페이지로 보낼 때 사용. 앱에서 예외 핸들러가 RedirectResponse로 변환."""
    def __init__(self, url: str = "/login", status_code: int = 302):
        self.url = url
        self.status_code = status_code
        super().__init__(url)
COOKIE_MAX_AGE = 86400 * 7  # 7일


def _constant_time_compare(a: str, b: str) -> bool:
    """타이밍 공격 완화용 상수 시간 문자열 비교."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _make_token(password: str, secret: str) -> str:
    """쿠키용 간단 서명 토큰 생성."""
    raw = f"{password}:{secret}"
    return hashlib.sha256(raw.encode()).hexdigest()


def verify_password(provided: str, expected: str) -> bool:
    """상수 시간 비교로 패스워드 검증."""
    if not expected:
        return False
    return _constant_time_compare(provided, expected)


def create_session_cookie(password: str, secret: str) -> tuple[str, str]:
    """쿠키 값·토큰 생성. (cookie_value, token) 반환."""
    token = _make_token(password, secret)
    return token, token


def verify_session_cookie(cookie_value: str | None, password: str, secret: str) -> bool:
    """쿠키가 기대한 서명 토큰과 일치하는지 검증."""
    if not cookie_value or not password:
        return False
    expected = _make_token(password, secret)
    return _constant_time_compare(cookie_value, expected)


def get_request_env(request: Request):
    """request scope(Workers 주입) 또는 state에서 env 조회."""
    env = getattr(request.state, "env", None)
    if env is None and "env" in request.scope:
        env = request.scope["env"]
    return env


def get_admin_password(request: Request) -> str:
    """env(Workers) 또는 os.environ에서 ADMIN_PASSWORD 조회."""
    env = get_request_env(request)
    if env is not None and hasattr(env, "get"):
        return env.get("ADMIN_PASSWORD", "") or ""
    import os
    return os.environ.get("ADMIN_PASSWORD", "")


def get_admin_email(request: Request) -> str:
    """env(Workers) 또는 os.environ에서 ADMIN_EMAIL 조회."""
    env = get_request_env(request)
    if env is not None and hasattr(env, "get"):
        return env.get("ADMIN_EMAIL", "") or ""
    import os
    return os.environ.get("ADMIN_EMAIL", "")


async def require_auth(
    request: Request,
    auth_cookie: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> None:
    """의존성: 미인증 시 /login으로 리다이렉트."""
    password = get_admin_password(request)
    # 패스워드 미설정 시 접근 허용(개발 모드)
    if not password:
        return
    secret = (password + "shortcrew-ops_salt")[:32]
    if not verify_session_cookie(auth_cookie, password, secret):
        raise AuthRequiredRedirect(url="/login", status_code=302)


def set_auth_cookie(response: Response, request: Request) -> None:
    """로그인 성공 후 인증 쿠키 설정."""
    password = get_admin_password(request)
    if not password:
        return
    secret = (password + "shortcrew-ops_salt")[:32]  # 일관성 위해 고정 길이
    _, token = create_session_cookie(password, secret)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """로그아웃 시 인증 쿠키 삭제."""
    response.delete_cookie(COOKIE_NAME, path="/")
