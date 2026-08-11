"""숏크루(Shortcrew) FastAPI entrypoint (루트 `main:app` — uvicorn / Docker와 동일).

라우트는 라우터 모듈로 분리되어 있다:
- app/admin/ops/        : /admin/api/ops/* JSON API
- app/webhooks/         : /webhooks/instagram
- app/admin/web_routes  : 백오피스 HTML(/admin/*)
- app/client/routes     : 공개(홈·허브·공개리뷰·레거시301·/api/*)
공통 인프라는 app/core/{config,db,templates,helpers,theme,access_log,errors}.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import load_env

_ROOT = Path(__file__).resolve().parent
load_env()  # 다른 모듈이 os.environ(DATABASE_URL 등)을 읽기 전에 .env 로드

# 내부 스케줄러(백필·리포트·큐레이션) 로그를 docker logs 로 내보낸다.
# 이게 없으면 앱 로거의 INFO 가 어디에도 남지 않아 "어제 왜 실패했나"를 사후 추적할 수 없다.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
for _noisy in ("httpx", "httpcore", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

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

class _NoCacheStatic(StaticFiles):
    """JS/CSS 는 배포 즉시 반영되도록 `Cache-Control: no-cache`(매번 재검증).

    브라우저·Cloudflare 가 etag 조건부 요청으로 검증 → 안 바뀌면 304(재다운로드 없음),
    바뀌면 새 파일. `?v=` 쿼리·파일명 해시 없이 캐시 지연을 없앤다. 이미지 등은 기본 유지.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if path.endswith((".js", ".css")):
            response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", _NoCacheStatic(directory=str(_ROOT / "static")), name="static")
register_error_handlers(app)

# 라우터 등록 순서: 어드민 HTML → 공개(catch-all `/{name_slug}` 가 마지막).
app.include_router(admin_router)
app.include_router(client_router)


@app.on_event("startup")
async def _startup_curation_scheduler() -> None:
    """n8n 의존 없이 앱 자체가 매일 1채널 큐레이션(env 로 켜짐)."""
    from app.admin.ops.services.curation_scheduler import start as _start_curation

    _start_curation()


@app.on_event("startup")
async def _startup_scripts_scheduler() -> None:
    """n8n 의존 없이 앱 자체가 매주 후기→대본 브리지 실행(env 로 켜짐)."""
    from app.admin.ops.services.scripts_scheduler import start as _start_scripts

    _start_scripts()


@app.on_event("startup")
async def _startup_ig_backfill_scheduler() -> None:
    """n8n 의존 없이 앱 자체가 과거영상을 계정별 소량씩 IG 백필(env 로 켜짐)."""
    from app.admin.ops.services.ig_backfill_scheduler import start as _start_ig_backfill

    _start_ig_backfill()


@app.on_event("startup")
async def _startup_ig_report_scheduler() -> None:
    """인스타 일일 운영 리포트를 앱이 직접 디스코드로 발송(env 로 켜짐)."""
    from app.admin.ops.services.ig_report_scheduler import start as _start_ig_report

    _start_ig_report()


@app.on_event("startup")
async def _startup_ig_token_refresh() -> None:
    """IG 장기토큰 40일 주기 자동갱신(만료 근절, env 로 켜짐)."""
    from app.admin.ops.services.ig_token_refresh import start as _start_ig_token

    _start_ig_token()
