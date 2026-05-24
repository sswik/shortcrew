"""어드민 리뷰 폼과 동일 규칙으로 Review INSERT (쇼츠 파이프라인·CLI용)."""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import Influencer, Product, Review

from app.admin.ops.services.shorts_name_normalize import names_equivalent
from app.client.review_html import split_shorts_review_cta

logger = logging.getLogger(__name__)


def resolve_influencer_slug_for_mall(db: Session, mall_influencer_slug_raw: str) -> str | None:
    """MALL_INFLUENCER_SLUG(쉼표 구분) 중 DB에 있는 name_slug."""
    raw = (mall_influencer_slug_raw or "").strip()
    if not raw:
        return None
    for chunk in raw.replace(";", ",").split(","):
        slug = chunk.strip().lower()
        if not slug:
            continue
        row = db.scalar(select(Influencer.id).where(func.lower(Influencer.name_slug) == slug))
        if row is not None:
            return slug
    return None


def find_product_for_sheet_product_name(
    db: Session,
    influencer_slug: str,
    sheet_product_name: str,
) -> Product | None:
    """동일 인플 상품 중 시트 상품명과 정규화 일치."""
    products = db.scalars(
        select(Product).where(func.lower(Product.influencer_slug) == influencer_slug.lower())
    ).all()
    for p in products:
        if names_equivalent(p.title, sheet_product_name):
            return p
    return None


def create_review_from_shorts_pipeline(
    db: Session,
    *,
    influencer_slug: str,
    product_id: int | None,
    title: str,
    content_html: str,
    source_youtube_video_id: str,
) -> tuple[Review | None, str | None]:
    """INSERT. 성공 시 (review, None), 중복·무결성 실패 시 (None, code)."""
    vid = (source_youtube_video_id or "").strip()
    if not vid:
        return None, "missing_video_id"
    inf = db.scalar(select(Influencer).where(Influencer.name_slug == influencer_slug))
    if inf is None:
        return None, "unknown_influencer"
    if product_id is not None:
        pid_row = db.scalar(select(Product.id).where(Product.id == product_id))
        if pid_row is None:
            return None, "unknown_product"

    existing = db.scalar(
        select(Review.id).where(
            Review.influencer_slug == influencer_slug,
            Review.source_youtube_video_id == vid,
        )
    )
    if existing is not None:
        return None, "duplicate_video_id"

    review = Review(
        influencer_slug=influencer_slug,
        product_id=product_id,
        title=(title or "").strip()[:255],
        content=content_html,
        source_youtube_video_id=vid,
    )
    db.add(review)
    try:
        db.commit()
        db.refresh(review)
        _body, dl = split_shorts_review_cta(content_html or "")
        logger.info(
            "review_published_shorts id=%s slug=%s product_id=%s video_id=%s "
            "content_chars=%s has_shorts_cta_block=%s parsed_cta_deeplink=%s",
            review.id,
            influencer_slug,
            product_id,
            vid,
            len(content_html or ""),
            "shorts-review-cta" in (content_html or ""),
            "yes" if dl else "no",
        )
        return review, None
    except IntegrityError:
        db.rollback()
        logger.info(
            "review_shorts_integrity_skip slug=%s video_id=%s", influencer_slug, vid[:16]
        )
        return None, "duplicate_video_id"
