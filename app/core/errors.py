"""예외 핸들러(HTML/JSON 분기). `register_error_handlers(app)` 로 앱에 등록한다."""
from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.admin.auth import AdminAuthRedirect
from app.core.templates import templates
from app.core.theme import _client_theme_context

logger = logging.getLogger(__name__)

_DEFAULT_404_MESSAGE = "요청하신 페이지가 없거나 주소가 변경되었을 수 있습니다."
_DEFAULT_500_MESSAGE = "잠시 후 다시 시도해 주세요. 문제가 계속되면 관리자에게 문의해 주세요."


def _request_wants_json_error(request: Request) -> bool:
    path = request.url.path
    if path.startswith("/api/") or path.startswith("/admin/api/"):
        return True
    accept = (request.headers.get("accept") or "").lower()
    return "application/json" in accept and "text/html" not in accept


def _http_exception_detail_text(exc: StarletteHTTPException) -> str | None:
    detail = exc.detail
    if isinstance(detail, str):
        text = detail.strip()
        return text or None
    return None


def _friendly_404_message(detail: str | None) -> str:
    if not detail:
        return _DEFAULT_404_MESSAGE
    if detail.lower() in {"not found", "not_found"}:
        return _DEFAULT_404_MESSAGE
    return detail


def register_error_handlers(app: FastAPI) -> None:
    """앱에 HTML/JSON 분기 예외 핸들러 3종을 등록한다."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
        if _request_wants_json_error(request):
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        if exc.status_code == 404:
            ctx = _client_theme_context()
            ctx["message"] = _friendly_404_message(_http_exception_detail_text(exc))
            return templates.TemplateResponse(request, "errors/404.html", ctx, status_code=404)
        if exc.status_code >= 500:
            ctx = _client_theme_context()
            ctx["message"] = _http_exception_detail_text(exc) or _DEFAULT_500_MESSAGE
            return templates.TemplateResponse(
                request, "errors/500.html", ctx, status_code=exc.status_code
            )
        ctx = _client_theme_context()
        ctx["message"] = _http_exception_detail_text(exc) or _DEFAULT_404_MESSAGE
        return templates.TemplateResponse(request, "errors/404.html", ctx, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        if _request_wants_json_error(request):
            return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
        ctx = _client_theme_context()
        ctx["message"] = _DEFAULT_500_MESSAGE
        return templates.TemplateResponse(request, "errors/500.html", ctx, status_code=500)

    @app.exception_handler(AdminAuthRedirect)
    async def _admin_auth_redirect_handler(request: Request, exc: AdminAuthRedirect) -> RedirectResponse:
        if exc.next_url:
            return RedirectResponse(
                url=f"/admin/login?next={quote(exc.next_url, safe='')}",
                status_code=302,
            )
        return RedirectResponse(url="/admin/login", status_code=302)
