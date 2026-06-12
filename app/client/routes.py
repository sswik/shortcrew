"""공개(클라이언트) 라우트: 홈·인플루언서 허브·공개 리뷰·레거시 301·몰 상품/클릭 API.

catch-all `/{name_slug}` 류는 이 파일 끝에 두며, main 에서 admin·api 등 고정 라우트보다 **나중에 include** 한다."""
from __future__ import annotations

import logging
import os
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import normalize_site_base
from app.core.db import get_db
from app.core.helpers import enrich_coupang_url_for_public
from app.core.templates import templates
from app.core.theme import _client_theme_context
from app.client.mall_sheet import resolve_mall_products_api
from app.client.mall_products_service import (
    DEFAULT_COUPANG_IMAGE_WORKER as _DEFAULT_COUPANG_IMAGE_WORKER,
    mall_products_response,
)
from app.client.mall_theme import parse_profile_meta_json
from app.client.profile_display import format_cue_card_tagline
from app.client.review_html import split_shorts_review_cta
from models import ClickLog, Influencer, Review

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
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


@router.get("/about", response_class=HTMLResponse)
def about_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "about.html", _client_theme_context())


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request) -> HTMLResponse:
    """개인정보처리방침(임시). Meta 앱 검수 제출용 공개 URL. catch-all 앞에 등록."""
    return templates.TemplateResponse(request, "privacy.html", _client_theme_context())


@router.get("/shop/{path_slug}", response_class=HTMLResponse, response_model=None)
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


@router.get("/api/mall-products", response_model=None)
def api_mall_products(channel_id: str = "") -> Response:
    return mall_products_response(channel_id)


@router.get("/reviews/{name_slug}", response_class=HTMLResponse)
def review_list_legacy_redirect(name_slug: str, db: Session = Depends(get_db)) -> Response:
    """레거시 `/reviews/{slug}` → `/{slug}/review` (301)."""
    name_slug = (name_slug or "").strip()
    if not name_slug or not db.scalar(select(Influencer).where(Influencer.name_slug == name_slug)):
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다.")
    return RedirectResponse(url=f"/{quote(name_slug, safe='')}/review", status_code=301)


@router.get("/reviews/{name_slug}/{review_id:int}", response_class=HTMLResponse)
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
        public_base = normalize_site_base(os.environ.get("PUBLIC_SITE_URL") or "")
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


@router.get("/{name_slug}/review/{review_id:int}", response_class=HTMLResponse)
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


@router.get("/{name_slug}/review", response_class=HTMLResponse)
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


@router.get("/{name_slug}/introduce", response_class=HTMLResponse)
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


@router.get("/{name_slug}", response_class=HTMLResponse, response_model=None)
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
