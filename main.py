"""숏크루(Shortcrew) FastAPI entrypoint (루트 `main:app` — uvicorn / Docker와 동일).

라우트는 라우터 모듈로 분리되어 있다:
- app/admin/ops/        : /admin/api/ops/* JSON API
- app/webhooks/         : /webhooks/instagram
- app/admin/web_routes  : 백오피스 HTML(/admin/*)
- app/client/routes     : 공개(홈·허브·공개리뷰·레거시301·/api/*)
공통 인프라는 app/core/{config,db,templates,helpers,theme,access_log,errors}.
"""
from __future__ import annotations

from pathlib import Path

from app.core.config import load_env

_ROOT = Path(__file__).resolve().parent
load_env()  # 다른 모듈이 os.environ(DATABASE_URL 등)을 읽기 전에 .env 로드

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.db import run_migrations
from app.core.access_log import AccessDetailLogMiddleware
from app.core.errors import register_error_handlers
from app.admin.ops.api_router import router as ops_api_router
from app.webhooks.instagram import router as ig_webhook_router
from app.admin.web_routes import router as admin_router
from app.client.routes import router as client_router

app = FastAPI(title="숏크루")
app.include_router(ops_api_router, prefix="/admin/api/ops", tags=["admin-ops"])
app.include_router(ig_webhook_router, tags=["webhooks"])  # 공개(인증 없음): /webhooks/instagram

_WWW_REDIRECT_HOST = "www.shortcrew.co.kr"
_APEX_PUBLIC_HOST = "shortcrew.co.kr"


@app.middleware("http")
async def redirect_www_to_apex(request: Request, call_next):
    """`www.shortcrew.co.kr` → `https://shortcrew.co.kr` (경로·쿼리 유지, 301)."""
    host = (request.url.hostname or "").strip().lower()
    if host == _WWW_REDIRECT_HOST:
        path = request.url.path or "/"
        query = request.url.query
        target = f"https://{_APEX_PUBLIC_HOST}{path}"
        if query:
            target += f"?{query}"
        return RedirectResponse(url=target, status_code=301)
    return await call_next(request)


app.add_middleware(AccessDetailLogMiddleware)

run_migrations()

app.mount("/static", StaticFiles(directory=str(_ROOT / "static")), name="static")
register_error_handlers(app)

# 라우터 등록 순서: 어드민 HTML → 공개(catch-all `/{name_slug}` 가 마지막).
app.include_router(admin_router)
app.include_router(client_router)
