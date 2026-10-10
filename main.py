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

from contextlib import asynccontextmanager

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

@asynccontextmanager
async def _lifespan(_: FastAPI):
    """앱 수명주기 — 기동 시 백그라운드 스케줄러를 띄운다.

    각 `start()` 는 자기 env 플래그(`*_ENABLED` / `*_LOOP`)를 보고 스스로 켜고 끄므로
    여기서는 조건 분기를 하지 않는다. Cloud Run 처럼 Cloud Scheduler 가 HTTP 로
    구동하는 환경에서는 `*_LOOP=0` 이라 전부 no-op 으로 끝난다.

    하나가 실패해도 앱은 떠야 한다(스케줄러는 부가기능, 웹 서빙이 본체) → 개별 try.
    과거 `@app.on_event("startup")` 5개였는데 deprecated 라 lifespan 으로 합쳤다.
    """
    from app.admin.ops.services.curation_scheduler import start as _start_curation
    from app.admin.ops.services.ig_backfill_scheduler import start as _start_ig_backfill
    from app.admin.ops.services.ig_report_scheduler import start as _start_ig_report
    from app.admin.ops.services.ig_token_refresh import start as _start_ig_token
    from app.admin.ops.services.scripts_scheduler import start as _start_scripts

    for name, starter in (
        ("curation", _start_curation),          # 매일 1채널 큐레이션
        ("scripts", _start_scripts),            # 매주 후기→대본 브리지
        ("ig_backfill", _start_ig_backfill),    # 과거영상 IG 백필
        ("ig_report", _start_ig_report),        # 일일 운영 리포트
        ("ig_token_refresh", _start_ig_token),  # IG 장기토큰 40일 갱신
    ):
        try:
            starter()
        except Exception:
            logging.getLogger(__name__).exception("스케줄러 기동 실패: %s", name)
    yield


app = FastAPI(title="숏크루", lifespan=_lifespan)
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



