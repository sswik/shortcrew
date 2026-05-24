"""숏크루(Shortcrew) FastAPI entrypoint (루트 `main:app` — uvicorn / Docker와 동일)."""

from __future__ import annotations

import json
import logging
import os
import time
from threading import Lock
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

import httpx

_ROOT = Path(__file__).resolve().parent


def _load_env_file() -> None:
    """`.env` 를 읽어, **현재 값이 비어 있을 때만** 키를 채운다(셸에 빈 CHANNEL_* 만 있어 .env 가 무시되는 문제 방지)."""
    path = _ROOT / ".env"
    if not path.is_file():
        return
    from dotenv import dotenv_values

    for key, val in dotenv_values(path).items():
        if val is None:
            continue
        cur = os.environ.get(key)
        if cur is None or str(cur).strip() == "":
            os.environ[key] = val


_load_env_file()


def _normalize_site_base(url: str) -> str:
    """`PUBLIC_SITE_URL` 등 — 스킴 없는 호스트·`//` 형태를 절대 URL로."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if not url.startswith(("http://", "https://")):
        return "https://" + url.lstrip("/")
    return url


from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Query, Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, joinedload

from app.admin.auth import (
    COOKIE_NAME,
    AdminAuthRedirect,
    admin_auth_enabled,
    admin_session_valid,
    clear_admin_session_cookie,
    require_admin,
    safe_admin_next,
    set_admin_session_cookie,
    admin_email_configured,
    verify_admin_login,
)
from app.admin.ops.api_router import router as ops_api_router
from app.client.mall_sheet import resolve_mall_products_api
from app.client.profile_display import format_cue_card_tagline
from app.client.mall_theme import (
    get_mall_theme,
    parse_profile_meta_json,
    theme_to_css_vars,
    theme_to_root_style,
    theme_to_style_tag,
    validate_mall_theme_json,
    validate_profile_meta_json,
)
from app.admin.ops.services.admin_review_products import (
    load_review_form_products,
    merge_saved_sheet_option_into_product_list,
)
from app.client.review_html import split_shorts_review_cta
from models import Base, ClickLog, Influencer, Product, Review, SessionLocal, engine

# 쿠팡 썸네일 프록시(Cloudflare Workers). 채널별 설정 없음 — 전역 env `COUPANG_IMAGE_WORKER_BASE`만 보며, 비우면 아래 URL.
_DEFAULT_COUPANG_IMAGE_WORKER = "https://image.shortcrew.co.kr/"
_MALL_PRODUCTS_CACHE_TTL_SECONDS = float(
    (os.environ.get("MALL_PRODUCTS_CACHE_TTL_SECONDS") or "45").strip() or "45"
)
_mall_products_cache_lock = Lock()
_mall_products_cache: dict[str, tuple[float, bytes, str]] = {}

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

_ACCESS_LOG_DIR = _ROOT / "logs"
_access_log_lock = Lock()


def _client_ip_from_request(request: Request) -> str:
    """프록시 뒤에서도 가능한 한 실제 클라이언트 IP 를 고른다."""
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[0].strip()
    xri = (request.headers.get("x-real-ip") or "").strip()
    if xri:
        return xri
    if request.client:
        return request.client.host or ""
    return ""


def _append_access_detail_log(
    *,
    request: Request,
    status_code: int,
    duration_ms: float,
) -> None:
    """접속자·요청 상세를 일별 텍스트 파일에 한 줄(JSON)로 남긴다."""
    now = datetime.now(KST)
    rec: dict[str, object] = {
        "ts": now.isoformat(timespec="milliseconds"),
        "method": request.method,
        "url": str(request.url),
        "path": request.url.path,
        "query": request.url.query or "",
        "client_ip": _client_ip_from_request(request),
        "forwarded_for": (request.headers.get("x-forwarded-for") or "").strip() or None,
        "user_agent": (request.headers.get("user-agent") or "").strip() or None,
        "referer": (request.headers.get("referer") or "").strip() or None,
        "accept_language": (request.headers.get("accept-language") or "").strip() or None,
        "host": (request.headers.get("host") or "").strip() or None,
        "scheme": request.url.scheme,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 3),
    }
    line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
    day = now.strftime("%Y-%m-%d")
    path = _ACCESS_LOG_DIR / f"access-{day}.txt"
    try:
        _ACCESS_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _access_log_lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except OSError as e:
        logger.warning("access_detail_log_write_failed path=%s err=%s", path, e)


class AccessDetailLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000.0
        _append_access_detail_log(
            request=request,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


def _log_review_admin_persist(*, event: str, review: Review) -> None:
    """저장 직후 본문·쇼츠 CTA 분리 결과를 INFO 로 남긴다."""
    raw = review.content or ""
    body, dl = split_shorts_review_cta(raw)
    logger.info(
        "review_admin_persist event=%s id=%s influencer_slug=%s product_id=%s "
        "title_chars=%s content_chars=%s has_shorts_cta_markup=%s "
        "parsed_cta_deeplink=%s body_chars_after_cta_strip=%s",
        event,
        review.id,
        review.influencer_slug,
        review.product_id,
        len((review.title or "").strip()),
        len(raw),
        "shorts-review-cta" in raw,
        "yes" if dl else "no",
        len(body or ""),
    )


app = FastAPI(title="숏크루")
app.include_router(ops_api_router, prefix="/admin/api/ops", tags=["admin-ops"])

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

Base.metadata.create_all(bind=engine)


def _ensure_click_log_schema() -> None:
    """기존 SQLite DB에 click_logs 신규 컬럼을 안전하게 추가한다."""
    with engine.begin() as conn:
        cols = {
            str(row[1]).strip().lower()
            for row in conn.execute(text("PRAGMA table_info(click_logs)")).fetchall()
        }
        if "raw_product_ref" not in cols:
            conn.execute(text("ALTER TABLE click_logs ADD COLUMN raw_product_ref VARCHAR(120)"))
        if "product_name_snapshot" not in cols:
            conn.execute(text("ALTER TABLE click_logs ADD COLUMN product_name_snapshot VARCHAR(255)"))
        if "deep_link_snapshot" not in cols:
            conn.execute(text("ALTER TABLE click_logs ADD COLUMN deep_link_snapshot VARCHAR(1200)"))
        if "client_user_agent" not in cols:
            conn.execute(text("ALTER TABLE click_logs ADD COLUMN client_user_agent VARCHAR(512)"))
        if "page_url" not in cols:
            conn.execute(text("ALTER TABLE click_logs ADD COLUMN page_url VARCHAR(800)"))
        if "referrer_snapshot" not in cols:
            conn.execute(text("ALTER TABLE click_logs ADD COLUMN referrer_snapshot VARCHAR(600)"))


_ensure_click_log_schema()


def _ensure_influencer_v2_columns() -> None:
    """SQLite: profile_meta_json, mall_theme_json for ShortCrew V2."""
    with engine.begin() as conn:
        cols = {
            str(row[1]).strip().lower()
            for row in conn.execute(text("PRAGMA table_info(influencers)")).fetchall()
        }
        if not cols:
            return
        if "profile_meta_json" not in cols:
            conn.execute(text("ALTER TABLE influencers ADD COLUMN profile_meta_json TEXT"))
        if "mall_theme_json" not in cols:
            conn.execute(text("ALTER TABLE influencers ADD COLUMN mall_theme_json TEXT"))


_ensure_influencer_v2_columns()


def _client_theme_context(influencer: Influencer | None = None) -> dict[str, object]:
    """Jinja context: mall theme CSS vars + parsed profile meta."""
    theme = get_mall_theme(influencer)
    meta = parse_profile_meta_json(
        getattr(influencer, "profile_meta_json", None) if influencer else None
    )
    return {
        "mall_theme": theme,
        "mall_theme_css": theme_to_css_vars(theme),
        "mall_theme_root_style": theme_to_root_style(theme),
        "mall_theme_style_tag": theme_to_style_tag(theme),
        "profile_meta": meta,
    }


def _ua_os_browser(ua: str | None) -> tuple[str, str]:
    """User-Agent 문자열에서 대략적인 OS·브라우저 라벨만 추출한다(외부 라이브러리 없음)."""
    u = (ua or "").strip()
    if not u:
        return ("—", "—")
    ul = u.lower()

    if "windows nt" in ul:
        os_label = "Windows"
    elif "android" in ul:
        os_label = "Android"
    elif "ipad" in ul or "cpu os " in ul or "iphone" in ul:
        os_label = "iPadOS" if "ipad" in ul else "iOS"
    elif "mac os x" in ul or "macintosh" in ul:
        os_label = "macOS"
    elif "linux" in ul:
        os_label = "Linux"
    else:
        os_label = "기타"

    if "edg/" in ul or "edgios" in ul or "edga/" in ul:
        browser_label = "Edge"
    elif "opr/" in ul or "opera" in ul:
        browser_label = "Opera"
    elif "samsungbrowser" in ul:
        browser_label = "Samsung Internet"
    elif "firefox/" in ul or "fxios/" in ul:
        browser_label = "Firefox"
    elif "crios/" in ul:
        browser_label = "Chrome"
    elif "chrome/" in ul and "chromium" not in ul:
        browser_label = "Chrome"
    elif "safari/" in ul and ("chrome/" not in ul and "crios/" not in ul):
        browser_label = "Safari"
    elif "safari/" in ul:
        browser_label = "Safari"
    else:
        browser_label = "기타"

    return (os_label, browser_label)


def _ellipsis_middle(s: str, *, max_chars: int) -> str:
    t = s.strip()
    if len(t) <= max_chars:
        return t
    if max_chars <= 3:
        return t[:max_chars]
    head = (max_chars - 1) // 2
    tail = max_chars - 1 - head
    return f"{t[:head]}…{t[-tail:]}"


def enrich_coupang_url_for_public(url: str, *, lptag: str) -> str:
    """쿠팡 도메인이면 lptag 쿼리를 보강한다(shop-products.js `withCoupangPartnerQuery`와 동일 규칙)."""
    u = (url or "").strip()
    if not u:
        return ""
    try:
        parts = urlparse(u)
    except ValueError:
        return u
    host = (parts.hostname or "").lower()
    if "coupang.com" not in host:
        return u
    q = list(parse_qsl(parts.query, keep_blank_values=True))
    keys_lower = {k.lower() for k, _ in q}
    lp = (lptag or "").strip()
    if lp and "lptag" not in keys_lower:
        q.append(("lptag", lp))
    new_query = urlencode(q, doseq=True)
    return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))


templates = Jinja2Templates(
    directory=[
        str(_ROOT / "app" / "client" / "templates"),
        str(_ROOT / "app" / "admin" / "templates"),
    ]
)
app.mount("/static", StaticFiles(directory=str(_ROOT / "static")), name="static")

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


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    influencers = db.scalars(select(Influencer).order_by(Influencer.display_name)).all()
    ctx = _client_theme_context()
    ctx["influencers"] = influencers
    ctx["influencers_profile_meta"] = {
        inf.name_slug: parse_profile_meta_json(inf.profile_meta_json) for inf in influencers
    }
    ctx["influencers_cue_tagline"] = {
        inf.name_slug: format_cue_card_tagline(
            inf.display_name,
            inf.name_slug,
            ctx["influencers_profile_meta"].get(inf.name_slug),
        )
        for inf in influencers
    }
    return templates.TemplateResponse(request, "home.html", ctx)


@app.get("/about", response_class=HTMLResponse)
def about_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "about.html", _client_theme_context())


@app.get("/shop/{path_slug}", response_class=HTMLResponse, response_model=None)
def shop_legacy_redirect(path_slug: str, db: Session = Depends(get_db)) -> Response:
    """레거시 `/shop/{slug}` → `/{name_slug}` (301)."""
    path_slug = (path_slug or "").strip()
    if not path_slug:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다.")
    influencer = db.scalar(select(Influencer).where(Influencer.shop_path_slug == path_slug))
    if influencer is None:
        influencer = db.scalar(select(Influencer).where(Influencer.name_slug == path_slug))
    if influencer is None:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다.")
    name_slug = (influencer.name_slug or "").strip()
    if not name_slug:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다.")
    return RedirectResponse(url=f"/{quote(name_slug, safe='')}", status_code=301)


@app.get("/api/mall-products", response_model=None)
def api_mall_products(channel_id: str = "") -> Response:
    """Apps Script 상품 JSON 을 서버가 대신 받아 돌려준다(브라우저 CORS 회피).

    `channel_id` 는 roster 의 `channel_id`(예: 201)로 채널을 고르고, 웹앱에 붙는 `?channel=` 값은
    `MALL_PRODUCTS_CHANNEL_PARAM`(비우면 `201`과 동일) — 샘플 short-mall-template 의 `APPS_SCRIPT_CHANNEL` 과 맞출 것.
    """
    from app.admin.ops.channels import get_channels

    cid = (channel_id or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="channel_id required")

    now = time.monotonic()
    with _mall_products_cache_lock:
        cached = _mall_products_cache.get(cid)
    if cached is not None:
        expires_at, cached_content, cached_media_type = cached
        if expires_at > now:
            return Response(content=cached_content, media_type=cached_media_type)
        with _mall_products_cache_lock:
            current = _mall_products_cache.get(cid)
            if current is not None and current[0] <= now:
                _mall_products_cache.pop(cid, None)

    channel = next((c for c in get_channels() if c.get("channel_id") == cid), None)
    if channel is None:
        raise HTTPException(status_code=404, detail="channel not found")
    base = (channel.get("mall_products_api_url") or "").strip()
    if not base:
        raise HTTPException(status_code=503, detail="mall_products_api_url not configured")
    chan_q = (channel.get("mall_products_channel_param") or "").strip() or cid
    sep = "?" if "?" not in base else "&"
    target = f"{base}{sep}channel={quote(chan_q, safe='')}"
    headers = {
        "Accept": "application/json, text/plain;q=0.9,*/*;q=0.8",
        "User-Agent": "Shortcrew/1.0 mall-products-proxy",
    }
    try:
        with httpx.Client(timeout=45.0, follow_redirects=True) as client:
            resp = client.get(target, headers=headers)
    except httpx.RequestError as e:
        logger.warning("mall_products_proxy request_error url=%s err=%s", target[:160], e)
        raise HTTPException(status_code=502, detail=f"upstream request failed: {e!s}") from e

    ct_lower = (resp.headers.get("content-type") or "").lower()
    body_preview = (resp.text or "")[:500].replace("\n", " ")

    if resp.status_code >= 400:
        logger.warning(
            "mall_products_proxy bad_status=%s ct=%s body=%s",
            resp.status_code,
            ct_lower,
            body_preview,
        )
        raise HTTPException(
            status_code=502,
            detail=f"upstream HTTP {resp.status_code}: {body_preview}",
        )
    if "text/html" in ct_lower and (resp.text or "").lstrip().lower().startswith("<!doctype"):
        logger.warning("mall_products_proxy got html url=%s", target[:160])
        raise HTTPException(
            status_code=502,
            detail=(
                "웹앱이 HTML을 돌려줬습니다(JSON 아님). 배포 '실행 URL'·액세스 '누구나'·"
                "CHANNEL_*_MALL_PRODUCTS_CHANNEL_PARAM(샘플 config 의 ?channel= 값) 확인."
            ),
        )

    ct = (resp.headers.get("content-type") or "application/json").split(";", 1)[0].strip()
    media_type = ct or "application/json"
    with _mall_products_cache_lock:
        _mall_products_cache[cid] = (
            time.monotonic() + max(1.0, _MALL_PRODUCTS_CACHE_TTL_SECONDS),
            resp.content,
            media_type,
        )
    return Response(content=resp.content, media_type=media_type)


@app.get("/reviews/{name_slug}", response_class=HTMLResponse)
def review_list_legacy_redirect(name_slug: str, db: Session = Depends(get_db)) -> Response:
    """레거시 `/reviews/{slug}` → `/{slug}/review` (301)."""
    name_slug = (name_slug or "").strip()
    if not name_slug or not db.scalar(select(Influencer).where(Influencer.name_slug == name_slug)):
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다.")
    return RedirectResponse(url=f"/{quote(name_slug, safe='')}/review", status_code=301)


@app.get("/reviews/{name_slug}/{review_id:int}", response_class=HTMLResponse)
def review_detail_legacy_redirect(name_slug: str, review_id: int, db: Session = Depends(get_db)) -> Response:
    """레거시 `/reviews/{slug}/{id}` → `/{slug}/review/{id}` (301)."""
    name_slug = (name_slug or "").strip()
    if not name_slug or not db.scalar(select(Influencer).where(Influencer.name_slug == name_slug)):
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다.")
    if not db.scalar(select(Review.id).where(Review.id == review_id, Review.influencer_slug == name_slug)):
        raise HTTPException(status_code=404, detail="리뷰를 찾을 수 없습니다.")
    return RedirectResponse(
        url=f"/{quote(name_slug, safe='')}/review/{review_id}",
        status_code=301,
    )


@app.get("/admin/login", response_model=None)
def admin_login_get(
    request: Request,
    next: str | None = None,
    auth_cookie: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> Response:
    if not admin_auth_enabled():
        return RedirectResponse(url="/admin/dashboard", status_code=302)
    if admin_session_valid(request, auth_cookie):
        return RedirectResponse(url="/admin/dashboard", status_code=302)
    n = safe_admin_next(next)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "next": n if n != "/admin/dashboard" else "",
            "error": None,
            "admin_email_configured": admin_email_configured(),
        },
    )


@app.post("/admin/login", response_model=None)
def admin_login_post(
    request: Request,
    email: str = Form(""),
    password: str = Form(...),
    next: str = Form(""),
) -> Response:
    if not admin_auth_enabled():
        return RedirectResponse(url="/admin/dashboard", status_code=303)
    if not verify_admin_login(email, password):
        err = (
            "이메일 또는 비밀번호가 올바르지 않습니다."
            if admin_email_configured()
            else "비밀번호가 올바르지 않습니다."
        )
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": err,
                "next": safe_admin_next(next),
                "admin_email_configured": admin_email_configured(),
            },
        )
    dest = safe_admin_next(next)
    resp = RedirectResponse(url=dest, status_code=303)
    set_admin_session_cookie(resp)
    return resp


@app.post("/admin/logout")
def admin_logout() -> RedirectResponse:
    if not admin_auth_enabled():
        return RedirectResponse(url="/admin/dashboard", status_code=303)
    resp = RedirectResponse(url="/admin/login", status_code=303)
    clear_admin_session_cookie(resp)
    return resp


@app.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    stats = {
        "influencers": db.scalar(select(func.count()).select_from(Influencer)) or 0,
        "products": db.scalar(select(func.count()).select_from(Product)) or 0,
        "reviews": db.scalar(select(func.count()).select_from(Review)) or 0,
        "clicks": db.scalar(select(func.count()).select_from(ClickLog)) or 0,
    }
    influencers = db.scalars(select(Influencer).order_by(Influencer.display_name)).all()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "stats": stats,
            "influencers": influencers,
        },
    )


def _parse_optional_product_id(raw: str, db: Session) -> int | None:
    raw_pid = (raw or "").strip()
    if not raw_pid:
        return None
    try:
        pid = int(raw_pid)
    except ValueError:
        raise HTTPException(status_code=400, detail="상품 ID가 올바르지 않습니다.")
    if pid <= 0:
        return None
    if db.scalar(select(Product.id).where(Product.id == pid)) is None:
        raise HTTPException(status_code=400, detail="상품을 찾을 수 없습니다.")
    return pid


def _review_sheet_fields_from_form(
    *,
    product_id_raw: str,
    pid: int | None,
    sheet_product_title: str,
    sheet_product_deeplink: str,
) -> tuple[str | None, str | None]:
    """DB 상품이면 시트 스냅샷 비움. 시트만(음수 value)이면 상품명·딥링크 저장."""
    if pid is not None:
        return None, None
    raw = (product_id_raw or "").strip()
    if not raw:
        return None, None
    try:
        v = int(raw)
    except ValueError:
        return None, None
    if v >= 0:
        return None, None
    t = (sheet_product_title or "").strip()[:255] or None
    d = (sheet_product_deeplink or "").strip()[:500] or None
    return t, d


@app.get("/admin/reviews/new", response_class=HTMLResponse)
def admin_reviews_new(
    request: Request,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    influencers = db.scalars(select(Influencer).order_by(Influencer.display_name)).all()
    first_slug = influencers[0].name_slug if influencers else ""
    products = load_review_form_products(db, first_slug)
    return templates.TemplateResponse(
        request,
        "reviews_form.html",
        {
            "influencers": influencers,
            "products": products,
            "review": None,
            "saved_sheet_option_id": None,
        },
    )


@app.get("/admin/reviews/{review_id}/edit", response_class=HTMLResponse)
def admin_reviews_edit(
    request: Request,
    review_id: int,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    review = db.scalar(
        select(Review).where(Review.id == review_id).options(joinedload(Review.product))
    )
    if review is None:
        raise HTTPException(status_code=404, detail="리뷰를 찾을 수 없습니다.")
    influencers = db.scalars(select(Influencer).order_by(Influencer.display_name)).all()
    products = load_review_form_products(
        db,
        review.influencer_slug,
        ensure_product_id=review.product_id,
    )
    products, saved_sheet_option_id = merge_saved_sheet_option_into_product_list(
        products,
        review_product_id=review.product_id or 0,
        review_id=review.id,
        review_sheet_title=review.sheet_product_title or "",
        review_sheet_deeplink=review.sheet_product_deeplink or "",
    )
    return templates.TemplateResponse(
        request,
        "reviews_form.html",
        {
            "influencers": influencers,
            "products": products,
            "review": review,
            "saved_sheet_option_id": saved_sheet_option_id,
        },
    )


@app.get("/admin/reviews/product-options")
def admin_reviews_product_options(
    _admin: None = Depends(require_admin),
    db: Session = Depends(get_db),
    influencer_slug: str = Query("", description="인플루언서 name_slug"),
    selected_product_id: int | None = Query(None, description="목록에 없어도 유지할 연결 상품 PK"),
    review_id: int | None = Query(None, description="수정 중 리뷰 id(시트만 저장분 옵션 병합)"),
) -> JSONResponse:
    """연결 상품 셀렉트 옵션: 시트 상품 탭에서 ``게시중`` 인 행만 DB와 매칭."""
    slug = (influencer_slug or "").strip()
    if not slug:
        return JSONResponse({"items": []})
    items = load_review_form_products(
        db, slug, ensure_product_id=selected_product_id
    )
    if review_id is not None:
        rev = db.scalar(select(Review).where(Review.id == review_id))
        if rev is not None and rev.influencer_slug == slug:
            items = merge_saved_sheet_option_into_product_list(
                items,
                review_product_id=rev.product_id or 0,
                review_id=rev.id,
                review_sheet_title=rev.sheet_product_title or "",
                review_sheet_deeplink=rev.sheet_product_deeplink or "",
            )[0]
    return JSONResponse(
        {
            "items": [
                {
                    "id": p.id,
                    "title": p.title,
                    "deeplink": p.deeplink or "",
                    "sheet_title": (p.sheet_title or "") if p.id < 0 else "",
                }
                for p in items
            ]
        }
    )


@app.get("/admin/reviews/{review_id}", response_class=HTMLResponse)
def admin_reviews_detail(
    request: Request,
    review_id: int,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    review = db.scalar(
        select(Review).where(Review.id == review_id).options(joinedload(Review.product))
    )
    if review is None:
        raise HTTPException(status_code=404, detail="리뷰를 찾을 수 없습니다.")
    return templates.TemplateResponse(request, "reviews_detail.html", {"review": review})


@app.get("/admin/reviews", response_class=HTMLResponse)
def admin_reviews_list(
    request: Request,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
    q: str = "",
    slug: str = "",
) -> HTMLResponse:
    influencers = db.scalars(select(Influencer).order_by(Influencer.display_name)).all()
    stmt = select(Review).options(joinedload(Review.product)).order_by(Review.created_at.desc())
    qn = (q or "").strip()
    if qn:
        stmt = stmt.where(Review.title.contains(qn))
    sn = (slug or "").strip()
    if sn:
        stmt = stmt.where(Review.influencer_slug == sn)
    reviews = db.scalars(stmt).all()
    return templates.TemplateResponse(
        request,
        "reviews.html",
        {
            "influencers": influencers,
            "reviews": reviews,
            "filter_q": qn,
            "filter_slug": sn,
        },
    )


@app.post("/admin/reviews")
def admin_reviews_post(
    _: None = Depends(require_admin),
    influencer_slug: str = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    product_id: str = Form(""),
    sheet_product_title: str = Form(""),
    sheet_product_deeplink: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    inf = db.scalar(select(Influencer).where(Influencer.name_slug == influencer_slug))
    if inf is None:
        raise HTTPException(status_code=400, detail="알 수 없는 인플루언서입니다.")
    pid = _parse_optional_product_id(product_id, db)
    st, sd = _review_sheet_fields_from_form(
        product_id_raw=product_id,
        pid=pid,
        sheet_product_title=sheet_product_title,
        sheet_product_deeplink=sheet_product_deeplink,
    )
    review = Review(
        influencer_slug=influencer_slug,
        product_id=pid,
        sheet_product_title=st,
        sheet_product_deeplink=sd,
        title=title.strip(),
        content=content,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    _log_review_admin_persist(event="create", review=review)
    return RedirectResponse(url=f"/admin/reviews/{review.id}", status_code=303)


@app.post("/admin/reviews/{review_id}/edit")
def admin_reviews_update(
    review_id: int,
    _: None = Depends(require_admin),
    influencer_slug: str = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    product_id: str = Form(""),
    sheet_product_title: str = Form(""),
    sheet_product_deeplink: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    review = db.scalar(select(Review).where(Review.id == review_id))
    if review is None:
        raise HTTPException(status_code=404, detail="리뷰를 찾을 수 없습니다.")
    inf = db.scalar(select(Influencer).where(Influencer.name_slug == influencer_slug))
    if inf is None:
        raise HTTPException(status_code=400, detail="알 수 없는 인플루언서입니다.")
    pid = _parse_optional_product_id(product_id, db)
    st, sd = _review_sheet_fields_from_form(
        product_id_raw=product_id,
        pid=pid,
        sheet_product_title=sheet_product_title,
        sheet_product_deeplink=sheet_product_deeplink,
    )
    review.influencer_slug = influencer_slug
    review.product_id = pid
    review.sheet_product_title = st
    review.sheet_product_deeplink = sd
    review.title = title.strip()
    review.content = content
    db.commit()
    db.refresh(review)
    _log_review_admin_persist(event="update", review=review)
    return RedirectResponse(url=f"/admin/reviews/{review_id}", status_code=303)


@app.get("/admin/influencers", response_class=HTMLResponse)
def admin_influencers(
    request: Request,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    influencers = db.scalars(select(Influencer).order_by(Influencer.display_name)).all()
    prod_rows = db.execute(
        select(Product.influencer_slug, func.count(Product.id)).group_by(Product.influencer_slug)
    ).all()
    prod_counts = {slug: int(cnt) for slug, cnt in prod_rows}
    rev_rows = db.execute(
        select(Review.influencer_slug, func.count(Review.id)).group_by(Review.influencer_slug)
    ).all()
    rev_counts = {slug: int(cnt) for slug, cnt in rev_rows}
    influencer_rows = [
        {
            "influencer": inf,
            "product_count": prod_counts.get(inf.name_slug, 0),
            "review_count": rev_counts.get(inf.name_slug, 0),
        }
        for inf in influencers
    ]
    return templates.TemplateResponse(
        request,
        "influencers.html",
        {"influencer_rows": influencer_rows},
    )


@app.get("/admin/influencers/{name_slug}/edit", response_class=HTMLResponse)
def admin_influencer_edit_get(
    request: Request,
    name_slug: str,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    inf = db.scalar(select(Influencer).where(Influencer.name_slug == name_slug))
    if inf is None:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다.")

    def _pretty_json(raw: str | None) -> str:
        if not raw or not str(raw).strip():
            return ""
        try:
            return json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            return str(raw)

    return templates.TemplateResponse(
        request,
        "influencer_edit.html",
        {
            "influencer": inf,
            "profile_meta_json_text": _pretty_json(inf.profile_meta_json),
            "mall_theme_json_text": _pretty_json(inf.mall_theme_json),
        },
    )


@app.post("/admin/influencers/{name_slug}/edit")
def admin_influencer_edit_post(
    name_slug: str,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
    display_name: str = Form(...),
    profile_image: str = Form(""),
    bio: str = Form(""),
    youtube_url: str = Form(""),
    instagram_url: str = Form(""),
    tiktok_url: str = Form(""),
    cover_image: str = Form(""),
    profile_meta_json: str = Form(""),
    mall_theme_json: str = Form(""),
) -> RedirectResponse:
    inf = db.scalar(select(Influencer).where(Influencer.name_slug == name_slug))
    if inf is None:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다.")
    meta_parsed, meta_err = validate_profile_meta_json(profile_meta_json)
    if meta_err:
        raise HTTPException(status_code=400, detail=meta_err)
    theme_parsed, theme_err = validate_mall_theme_json(mall_theme_json)
    if theme_err:
        raise HTTPException(status_code=400, detail=theme_err)
    inf.display_name = display_name.strip()
    inf.profile_image = (profile_image or "").strip()
    inf.bio = (bio or "").strip() or None
    inf.youtube_url = (youtube_url or "").strip()
    inf.instagram_url = (instagram_url or "").strip()
    inf.tiktok_url = (tiktok_url or "").strip()
    inf.cover_image = (cover_image or "").strip()
    inf.profile_meta_json = json.dumps(meta_parsed, ensure_ascii=False) if meta_parsed else None
    inf.mall_theme_json = json.dumps(theme_parsed, ensure_ascii=False) if theme_parsed else None
    db.commit()
    return RedirectResponse(url="/admin/influencers", status_code=303)


@app.get("/admin/products", response_class=HTMLResponse)
def admin_products(
    request: Request,
    _: None = Depends(require_admin),
) -> HTMLResponse:
    """쿠팡 검색·시트 전송·등록 상품(sample/ops dashboard 동등, API는 /admin/api/ops)."""
    return templates.TemplateResponse(request, "products.html", {})


@app.get("/admin/sheets", response_class=HTMLResponse)
def admin_sheets(
    request: Request,
    _: None = Depends(require_admin),
) -> HTMLResponse:
    sheets_env = {
        "service_account_configured": bool((os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") or "").strip()),
        "gemini_configured": bool((os.environ.get("GOOGLE_GEMINI_KEY") or "").strip()),
    }
    return templates.TemplateResponse(
        request,
        "sheets.html",
        {"sheets_env": sheets_env},
    )


@app.get("/admin/logs", response_class=HTMLResponse)
def admin_logs(
    request: Request,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    log_limit = 200
    stmt = (
        select(
            ClickLog.id,
            ClickLog.created_at,
            ClickLog.influencer_slug,
            ClickLog.product_id,
            func.coalesce(Product.title, ClickLog.product_name_snapshot).label("product_title"),
            ClickLog.raw_product_ref,
            ClickLog.deep_link_snapshot,
            ClickLog.client_user_agent,
            ClickLog.page_url,
            ClickLog.referrer_snapshot,
        )
        .outerjoin(Product, ClickLog.product_id == Product.id)
        .order_by(ClickLog.created_at.desc())
        .limit(log_limit)
    )
    log_rows = []
    for row in db.execute(stmt).mappings().all():
        item = dict(row)
        created_at = item.get("created_at")
        if created_at is None:
            item["created_at_kst"] = ""
        else:
            created_at_utc = (
                created_at.replace(tzinfo=timezone.utc)
                if created_at.tzinfo is None
                else created_at.astimezone(timezone.utc)
            )
            item["created_at_kst"] = created_at_utc.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
        ua = item.get("client_user_agent")
        if isinstance(ua, str):
            os_l, br_l = _ua_os_browser(ua)
        else:
            os_l, br_l = ("—", "—")
        item["access_os"] = os_l
        item["access_browser"] = br_l
        ps = str(item.get("page_url") or "").strip()
        rs = str(item.get("referrer_snapshot") or "").strip()
        item["page_url_display"] = _ellipsis_middle(ps, max_chars=56) if ps else "—"
        item["referrer_display"] = _ellipsis_middle(rs, max_chars=40) if rs else "—"
        item["page_url_tooltip"] = ps
        item["referrer_tooltip"] = rs
        item["client_ua_tooltip"] = (ua or "").strip() if isinstance(ua, str) else ""
        log_rows.append(item)
    return templates.TemplateResponse(
        request,
        "logs.html",
        {"log_rows": log_rows, "log_limit": log_limit},
    )


@app.post("/api/click")
def api_click(
    influencer_slug: str = Form(""),
    pump_slug: str = Form(""),
    legacy_pump_slug: str = Form(""),
    product_id: str = Form(...),
    product_name: str | None = Form(default=None),
    deep_link: str | None = Form(default=None),
    client_user_agent: str | None = Form(default=None),
    page_url: str | None = Form(default=None),
    referrer_snapshot: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    normalized_influencer_slug = (influencer_slug or "").strip()
    normalized_pump_slug = (pump_slug or "").strip()
    normalized_legacy_pump_slug = (legacy_pump_slug or "").strip()
    resolved_influencer = (
        normalized_influencer_slug
        or normalized_pump_slug
        or normalized_legacy_pump_slug
    )
    if not resolved_influencer:
        raise HTTPException(status_code=400, detail="influencer_slug required")
    if not normalized_influencer_slug and (normalized_pump_slug or normalized_legacy_pump_slug):
        logger.info(
            "api_click legacy pump_slug fallback used: influencer_slug=%s",
            resolved_influencer,
        )
    raw_product_ref = (product_id or "").strip()[:120]
    raw = raw_product_ref.split(".", 1)[0][:32]
    product_name_snapshot = (product_name or "").strip()[:255] or None
    deep_link_snapshot = (deep_link or "").strip()[:1200] or None
    ua_snap = (client_user_agent or "").strip()[:512] or None
    page_snap = (page_url or "").strip()[:800] or None
    ref_snap = (referrer_snapshot or "").strip()[:600] or None
    try:
        pid = int(raw) if raw else 0
    except ValueError:
        pid = 0
    db.add(
        ClickLog(
            influencer_slug=resolved_influencer,
            product_id=pid,
            raw_product_ref=raw_product_ref or None,
            product_name_snapshot=product_name_snapshot,
            deep_link_snapshot=deep_link_snapshot,
            client_user_agent=ua_snap,
            page_url=page_snap,
            referrer_snapshot=ref_snap,
        )
    )
    db.commit()
    return {"ok": "1"}


# ----- 공개 인플 허브 `/{name_slug}` (admin·api 등 고정 라우트보다 반드시 아래에 둔다) -----

_RESERVED_PUBLIC_SLUGS = frozenset(
    {
        "about",
        "api",
        "static",
        "health",
    },
)


def _public_slug_is_reserved(slug: str) -> bool:
    """`/docs`, `/openapi.json` 등은 FastAPI가 먼저 등록하므로 여기서는 짧은 시스템 단어만 막는다."""
    s = (slug or "").strip().lower()
    if not s:
        return True
    if s in _RESERVED_PUBLIC_SLUGS:
        return True
    return False


def _influencer_hub_page(
    request: Request,
    db: Session,
    *,
    influencer: Influencer,
    hub_tab: str,
) -> HTMLResponse:
    if hub_tab not in ("products", "reviews", "channel"):
        hub_tab = "products"
    name_slug = influencer.name_slug
    shop_path = (influencer.shop_path_slug or "").strip()
    mall_api_url, mall_channel_id = resolve_mall_products_api(
        name_slug,
        shop_path or None,
    )
    worker = (os.environ.get("COUPANG_IMAGE_WORKER_BASE") or "").strip().rstrip("/")
    if not worker:
        worker = _DEFAULT_COUPANG_IMAGE_WORKER.strip().rstrip("/")
    mall_fetch_url = ""
    if mall_api_url and mall_channel_id:
        public_base = _normalize_site_base(os.environ.get("PUBLIC_SITE_URL") or "")
        if not public_base:
            public_base = str(request.base_url).rstrip("/")
        mall_fetch_url = f"{public_base}/api/mall-products?channel_id={quote(mall_channel_id, safe='')}"
    partners_lptag = (
        (os.environ.get("COUPANG_PARTNERS_LPTAG") or os.environ.get("COUPANG_LPTAG") or "")
        .strip()
    )
    shop_page_config = {
        "mallProductsFetchUrl": mall_fetch_url,
        "mallProductsApiUrl": mall_api_url,
        "mallApiChannel": mall_channel_id,
        "coupangImageWorkerBase": worker + "/",
        "influencerSlug": name_slug,
        "coupangPartnersLptag": partners_lptag,
    }
    reviews = db.scalars(
        select(Review)
        .where(Review.influencer_slug == name_slug)
        .order_by(Review.created_at.desc())
    ).all()
    ctx = _client_theme_context(influencer)
    ctx.update(
        {
            "influencer": influencer,
            "shop_page_config": shop_page_config,
            "reviews": reviews,
            "hub_tab": hub_tab,
        }
    )
    return templates.TemplateResponse(request, "shop.html", ctx)


@app.get("/{name_slug}/review/{review_id:int}", response_class=HTMLResponse)
def public_review_detail(
    request: Request,
    name_slug: str,
    review_id: int,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if _public_slug_is_reserved(name_slug):
        raise HTTPException(status_code=404, detail="Not Found")
    influencer = db.scalar(select(Influencer).where(Influencer.name_slug == name_slug))
    if influencer is None:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다.")
    review = db.scalar(
        select(Review)
        .where(Review.id == review_id, Review.influencer_slug == name_slug)
        .options(joinedload(Review.product))
    )
    if review is None:
        raise HTTPException(status_code=404, detail="리뷰를 찾을 수 없습니다.")
    partners_lptag = (
        (os.environ.get("COUPANG_PARTNERS_LPTAG") or os.environ.get("COUPANG_LPTAG") or "")
        .strip()
    )
    buy_url = ""
    if review.product_id and review.product and (review.product.coupang_url or "").strip():
        buy_url = enrich_coupang_url_for_public(
            review.product.coupang_url,
            lptag=partners_lptag,
        )
    elif (review.sheet_product_deeplink or "").strip():
        buy_url = enrich_coupang_url_for_public(
            (review.sheet_product_deeplink or "").strip(),
            lptag=partners_lptag,
        )
    review_body_html, shorts_deeplink = split_shorts_review_cta(review.content or "")
    logger.info(
        "review_public_view id=%s path_slug=%s influencer_slug=%s product_id=%s "
        "content_chars=%s body_chars_after_cta_strip=%s footer_shorts_deeplink=%s "
        "mall_buy_url=%s",
        review.id,
        name_slug,
        review.influencer_slug,
        review.product_id,
        len(review.content or ""),
        len(review_body_html or ""),
        "yes" if shorts_deeplink else "no",
        "yes" if buy_url else "no",
    )
    ctx = _client_theme_context(influencer)
    ctx.update(
        {
            "influencer": influencer,
            "review": review,
            "buy_url": buy_url,
            "review_body_html": review_body_html,
            "shorts_deeplink": shorts_deeplink,
        }
    )
    return templates.TemplateResponse(request, "review_detail.html", ctx)


@app.get("/{name_slug}/review", response_class=HTMLResponse)
def public_influencer_reviews_tab(
    request: Request,
    name_slug: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if _public_slug_is_reserved(name_slug):
        raise HTTPException(status_code=404, detail="Not Found")
    influencer = db.scalar(select(Influencer).where(Influencer.name_slug == name_slug))
    if influencer is None:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다.")
    return _influencer_hub_page(request, db, influencer=influencer, hub_tab="reviews")


@app.get("/{name_slug}/introduce", response_class=HTMLResponse)
def public_influencer_introduce_tab(
    request: Request,
    name_slug: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if _public_slug_is_reserved(name_slug):
        raise HTTPException(status_code=404, detail="Not Found")
    influencer = db.scalar(select(Influencer).where(Influencer.name_slug == name_slug))
    if influencer is None:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다.")
    return _influencer_hub_page(request, db, influencer=influencer, hub_tab="channel")


@app.get("/{name_slug}", response_class=HTMLResponse, response_model=None)
def public_influencer_hub(
    request: Request,
    name_slug: str,
    db: Session = Depends(get_db),
) -> Response | HTMLResponse:
    ns = (name_slug or "").strip()
    if not ns:
        raise HTTPException(status_code=404, detail="Not Found")
    if ns.lower() == "admin":
        return RedirectResponse(url="/admin/login", status_code=302)
    if _public_slug_is_reserved(ns):
        raise HTTPException(status_code=404, detail="Not Found")
    influencer = db.scalar(select(Influencer).where(Influencer.name_slug == ns))
    if influencer is None:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다.")
    return _influencer_hub_page(request, db, influencer=influencer, hub_tab="products")
