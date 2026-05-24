"""관리자 이메일·패스워드·세션 쿠키.

`ADMIN_PASSWORD` 미설정 시(로컬 개발) 백오피스 무인증 허용.
`ADMIN_EMAIL` 이 설정되면 로그인 시 해당 이메일과 비밀번호를 모두 검사한다.
`ADMIN_EMAIL` 이 비어 있으면(레거시) 비밀번호만 검사한다.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Annotated

from fastapi import Cookie, Request
from fastapi.responses import RedirectResponse, Response

COOKIE_NAME = "shortcrew_admin"
COOKIE_MAX_AGE = 86400 * 7
_LOGIN_PATH = "/admin/login"
_SALT = "shortcrew_admin_session"


class AdminAuthRedirect(Exception):
    """미인증 시 로그인으로 보냄. `main`에서 `RedirectResponse`로 변환."""

    def __init__(self, next_url: str = "") -> None:
        self.next_url = next_url
        super().__init__("admin auth required")


def _admin_password() -> str:
    return (os.environ.get("ADMIN_PASSWORD") or "").strip()


def _admin_email() -> str:
    return (os.environ.get("ADMIN_EMAIL") or "").strip()


def admin_email_configured() -> bool:
    """True면 로그인 시 이메일까지 검증한다."""
    return bool(_admin_email())


def admin_auth_enabled() -> bool:
    """`ADMIN_PASSWORD`가 비어 있으면 False — 이 경우 백오피스는 무인증(개발용)."""
    return bool(_admin_password())


def safe_admin_next(raw: str | None) -> str:
    """오픈 리다이렉트 방지: `/admin` 하위 상대 경로만 허용."""
    s = (raw or "").strip()
    if not s.startswith("/admin"):
        return "/admin/dashboard"
    if s.startswith("//") or "://" in s or "\r" in s or "\n" in s:
        return "/admin/dashboard"
    return s


def _normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def verify_password(provided: str, expected: str) -> bool:
    if not expected:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def verify_admin_password(provided: str) -> bool:
    return verify_password((provided or "").strip(), _admin_password())


def verify_admin_login(email: str, password: str) -> bool:
    """비밀번호 일치 + (설정 시) 관리자 이메일 일치."""
    if not verify_admin_password(password):
        return False
    configured = _admin_email()
    if not configured:
        return True
    return _normalize_email(email) == _normalize_email(configured)


def _session_basis() -> str:
    """쿠키 토큰 계산용 문자열. 이메일이 있으면 계정 단위로 묶는다."""
    p = _admin_password()
    e = _admin_email()
    if e:
        return f"{_normalize_email(e)}:{p}"
    return p


def _session_token_from_env() -> str:
    basis = _session_basis()
    secret = (basis + _SALT)[:64]
    raw = f"{basis}:{secret}"
    return hashlib.sha256(raw.encode()).hexdigest()


def verify_session_cookie(cookie_value: str | None) -> bool:
    if not cookie_value or not _admin_password():
        return False
    expected = _session_token_from_env()
    return hmac.compare_digest(cookie_value.encode("utf-8"), expected.encode("utf-8"))


def admin_session_valid(request: Request, auth_cookie: str | None) -> bool:
    if not _admin_password():
        return True
    return verify_session_cookie(auth_cookie)


def set_admin_session_cookie(response: Response) -> None:
    if not _admin_password():
        return
    token = _session_token_from_env()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/admin",
    )


def clear_admin_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/admin")


async def require_admin(
    request: Request,
    auth_cookie: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> None:
    if not _admin_password():
        return
    if verify_session_cookie(auth_cookie):
        return
    next_url = request.url.path
    if request.url.query:
        next_url = f"{next_url}?{request.url.query}"
    if next_url.startswith(_LOGIN_PATH):
        next_url = ""
    raise AdminAuthRedirect(next_url)
