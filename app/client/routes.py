"""공개(클라이언트) 라우트: 홈·펌프 몰 허브(상품/블로그/소개)·몰 상품/클릭 API·블로그 API.

catch-all `/{name_slug}` 류는 이 파일 끝에 두며, main 에서 admin·api 등 고정 라우트보다 **나중에 include** 한다.
00식 통합: 몰은 `pumps` 테이블 기반(persona/influencer 아님). 상품은 시트 JSON 직독.
"""
from __future__ import annotations

import logging
import os
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import normalize_site_base
from app.core.db import get_db
from app.core.templates import templates
from app.client.mall_sheet import resolve_mall_products_api
from app.client.mall_products_service import (
    DEFAULT_COUPANG_IMAGE_WORKER as _DEFAULT_COUPANG_IMAGE_WORKER,
    mall_products_response,
)
from app.client.mall_theme import pump_mall_theme, tap_highlight_rgba
from app.admin.ops.services.blog_service import youtube_embed_html
from models import BlogPost, ClickLog, Pump

logger = logging.getLogger(__name__)

router = APIRouter()

_HUB_TABS = ("products", "blog", "channel")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    pumps = db.scalars(select(Pump).order_by(Pump.display_name)).all()
    ctx = {"pumps": pumps}
    return templates.TemplateResponse(request, "home.html", ctx)


@router.get("/about", response_class=HTMLResponse)
def about_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "about.html", {})


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request) -> HTMLResponse:
    """개인정보처리방침(임시). Meta 앱 검수 제출용 공개 URL. catch-all 앞에 등록."""
    return templates.TemplateResponse(request, "privacy.html", {})


@router.get("/shop/{path_slug}", response_class=HTMLResponse, response_model=None)
def shop_legacy_redirect(path_slug: str, db: Session = Depends(get_db)) -> Response:
    """레거시 `/shop/{slug}` → `/{name_slug}` (301)."""
    path_slug = (path_slug or "").strip()
    if not path_slug:
        raise HTTPException(status_code=404, detail="몰을 찾을 수 없습니다.")
    pump = db.scalar(select(Pump).where(Pump.shop_path_slug == path_slug))
    if pump is None:
        pump = db.scalar(select(Pump).where(Pump.name_slug == path_slug))
    if pump is None:
        raise HTTPException(status_code=404, detail="몰을 찾을 수 없습니다.")
    name_slug = (pump.name_slug or "").strip()
    if not name_slug:
        raise HTTPException(status_code=404, detail="몰을 찾을 수 없습니다.")
    return RedirectResponse(url=f"/{quote(name_slug, safe='')}", status_code=301)


@router.get("/api/mall-products", response_model=None)
def api_mall_products(channel_id: str = "") -> Response:
    return mall_products_response(channel_id)


@router.get("/api/blog", response_model=None)
def api_blog(slug: str = "", db: Session = Depends(get_db)) -> JSONResponse:
    """몰 블로그 탭 목록 API. 해당 펌프의 published 글을 최신순으로."""
    slug = (slug or "").strip()
    if not slug:
        return JSONResponse({"slug": slug, "posts": []})
    rows = db.scalars(
        select(BlogPost)
        .where(BlogPost.pump_slug == slug, BlogPost.status == "published")
        .order_by(BlogPost.created_at.desc())
    ).all()
    posts = [
        {
            "id": p.id,
            "title": p.title,
            "excerpt": p.excerpt,
            "thumbnail": p.thumbnail or p.product_image_url,
            "url": f"/{quote(slug, safe='')}/blog/{p.id}",
            "date": p.created_at.strftime("%Y-%m-%d") if p.created_at else "",
        }
        for p in rows
    ]
    return JSONResponse({"slug": slug, "posts": posts})


@router.post("/api/click")
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
    resolved_slug = (
        (pump_slug or "").strip()
        or (influencer_slug or "").strip()
        or (legacy_pump_slug or "").strip()
    )
    if not resolved_slug:
        raise HTTPException(status_code=400, detail="pump_slug required")
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
            influencer_slug=resolved_slug,
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


# ----- 공개 펌프 몰 허브 `/{name_slug}` (admin·api 등 고정 라우트보다 반드시 아래에 둔다) -----

_RESERVED_PUBLIC_SLUGS = frozenset({"about", "api", "static", "health"})


def _public_slug_is_reserved(slug: str) -> bool:
    s = (slug or "").strip().lower()
    if not s:
        return True
    return s in _RESERVED_PUBLIC_SLUGS


def _pump_hub_page(request: Request, *, pump: Pump, hub_tab: str) -> HTMLResponse:
    if hub_tab not in _HUB_TABS:
        hub_tab = "products"
    name_slug = pump.name_slug
    shop_path = (pump.shop_path_slug or "").strip()
    mall_api_url, mall_channel_id = resolve_mall_products_api(name_slug, shop_path or None)
    worker = (os.environ.get("COUPANG_IMAGE_WORKER_BASE") or "").strip().rstrip("/")
    if not worker:
        worker = _DEFAULT_COUPANG_IMAGE_WORKER.strip().rstrip("/")
    public_base = normalize_site_base(os.environ.get("PUBLIC_SITE_URL") or "")
    if not public_base:
        public_base = str(request.base_url).rstrip("/")
    mall_fetch_url = ""
    if mall_channel_id:
        # 같은 오리진 상대경로 — PUBLIC_SITE_URL/호스트 무관하게 동작(로컬·프록시 안전).
        mall_fetch_url = f"/api/mall-products?channel_id={quote(mall_channel_id, safe='')}"
    partners_lptag = (
        os.environ.get("COUPANG_PARTNERS_LPTAG") or os.environ.get("COUPANG_LPTAG") or ""
    ).strip()
    mall_theme = pump_mall_theme(pump)
    shop_page_config = {
        "mallProductsFetchUrl": mall_fetch_url,
        "mallProductsApiUrl": mall_api_url,
        "mallApiChannel": mall_channel_id,
        "coupangImageWorkerBase": worker + "/",
        "pumpSlug": name_slug,
        "coupangPartnersLptag": partners_lptag,
        "mallUrl": f"{public_base}/{quote(name_slug, safe='')}",
        "theme": mall_theme,
    }
    ctx = {
        "pump": pump,
        "shop_page_config": shop_page_config,
        "hub_tab": hub_tab,
        "mall_theme": mall_theme,
        "mall_theme_tap": tap_highlight_rgba(mall_theme.get("accent", "")),
    }
    return templates.TemplateResponse(request, "shop.html", ctx)


def _load_pump_or_404(db: Session, name_slug: str) -> Pump:
    if _public_slug_is_reserved(name_slug):
        raise HTTPException(status_code=404, detail="Not Found")
    pump = db.scalar(select(Pump).where(Pump.name_slug == name_slug))
    if pump is None:
        raise HTTPException(status_code=404, detail="몰을 찾을 수 없습니다.")
    return pump


@router.get("/{name_slug}/introduce", response_class=HTMLResponse)
def public_pump_introduce_tab(
    request: Request, name_slug: str, db: Session = Depends(get_db)
) -> HTMLResponse:
    pump = _load_pump_or_404(db, name_slug)
    return _pump_hub_page(request, pump=pump, hub_tab="channel")


@router.get("/{name_slug}/blog", response_class=HTMLResponse)
def public_pump_blog_tab(
    request: Request, name_slug: str, db: Session = Depends(get_db)
) -> HTMLResponse:
    pump = _load_pump_or_404(db, name_slug)
    return _pump_hub_page(request, pump=pump, hub_tab="blog")


@router.get("/{name_slug}/blog/{post_id:int}", response_class=HTMLResponse)
def public_blog_detail(
    request: Request, name_slug: str, post_id: int, db: Session = Depends(get_db)
) -> HTMLResponse:
    """블로그 개별 글(SEO 페이지). 본문 + 상품이미지 + 마지막에 유튜브 임베드."""
    pump = _load_pump_or_404(db, name_slug)
    post = db.scalar(
        select(BlogPost).where(
            BlogPost.id == post_id,
            BlogPost.pump_slug == pump.name_slug,
            BlogPost.status == "published",
        )
    )
    if post is None:
        raise HTTPException(status_code=404, detail="글을 찾을 수 없습니다.")
    mall_theme = pump_mall_theme(pump)
    partners_lptag = (
        os.environ.get("COUPANG_PARTNERS_LPTAG") or os.environ.get("COUPANG_LPTAG") or ""
    ).strip()
    ctx = {
        "pump": pump,
        "post": post,
        "yt_embed_html": youtube_embed_html(post.youtube_url or ""),
        "buy_url": post.product_deeplink or "",
        "partners_lptag": partners_lptag,
        "mall_theme": mall_theme,
        "mall_theme_tap": tap_highlight_rgba(mall_theme.get("accent", "")),
    }
    return templates.TemplateResponse(request, "blog_detail.html", ctx)


@router.get("/{name_slug}", response_class=HTMLResponse, response_model=None)
def public_pump_hub(
    request: Request, name_slug: str, db: Session = Depends(get_db)
) -> Response | HTMLResponse:
    ns = (name_slug or "").strip()
    if not ns:
        raise HTTPException(status_code=404, detail="Not Found")
    if ns.lower() == "admin":
        return RedirectResponse(url="/admin/login", status_code=302)
    pump = _load_pump_or_404(db, ns)
    return _pump_hub_page(request, pump=pump, hub_tab="products")
