"""채널·몰 공개 URL과 쿠팡 파트너스 subId(추적 슬러그) 결정."""

from __future__ import annotations

import os
import re

from fastapi import Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.admin.ops.channels.env_names import channel_env
from models import Influencer

_SLUG_SAFE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def public_site_origin(*, request: Request | None = None) -> str:
    """`PUBLIC_SITE_URL` 우선, 없으면 요청 호스트 기준 절대 origin."""
    raw = (os.environ.get("PUBLIC_SITE_URL") or "").strip().rstrip("/")
    if raw:
        return raw
    if request is not None:
        return str(request.base_url).rstrip("/")
    return ""


def influencer_for_channel(db: Session | None, channel: dict) -> Influencer | None:
    """채널 `mall_pump_slug` 가 DB 인플루언서 `name_slug` 또는 `shop_path_slug` 와 일치하면 반환."""
    if db is None:
        return None
    mall = (channel.get("mall_pump_slug") or "").strip()
    if not mall:
        return None
    return db.scalar(
        select(Influencer).where(
            or_(Influencer.name_slug == mall, Influencer.shop_path_slug == mall),
        ),
    )


def shop_public_path_slug(influencer: Influencer | None, channel: dict) -> str:
    """공개 몰 경로 `/{name_slug}` 에 쓰는 슬러그(브라우저 URL은 항상 `Influencer.name_slug`)."""
    if influencer is not None:
        return (influencer.name_slug or "").strip()
    mall = (channel.get("mall_pump_slug") or "").strip()
    if mall and _SLUG_SAFE.match(mall.lower()):
        return mall.lower()
    return (channel.get("channel_id") or "").strip()


def public_shop_page_url(*, origin: str, shop_path_slug: str) -> str:
    """`origin` + 공개 인플 경로 `/{slug}` (인자 이름은 하위 호환용)."""
    if not (origin and shop_path_slug):
        return ""
    slug = shop_path_slug.strip().lstrip("/")
    return f"{origin.rstrip('/')}/{slug}"


def coupang_sub_id_prefix(channel_id: str) -> str:
    """쿠팡 subId 접두(채널 토큰). `CHANNEL_*_COUPANG_SUB_ID_PREFIX` → 전역 `COUPANG_SUB_ID_PREFIX` → `sub{channel_id}`."""
    cid = (channel_id or "").strip() or "unknown"
    p = (os.environ.get(channel_env(cid, "COUPANG_SUB_ID_PREFIX")) or "").strip()
    if p:
        return p
    p = (os.environ.get("COUPANG_SUB_ID_PREFIX") or "").strip()
    if p:
        return p
    return f"sub{cid}"


def coupang_sub_id_for_public_shop(
    *,
    mall_channel: dict | None,
    influencer: Influencer,
    db: Session | None,
) -> str:
    """공개 몰 페이지에 내려줄 subId. 채널 매칭 시 `coupang_sub_id_for_channel`, 없으면 전역 접두 + 인플 슬러그."""
    if mall_channel:
        return coupang_sub_id_for_channel(mall_channel, db=db)
    slug = (influencer.shop_path_slug or "").strip() or (influencer.name_slug or "").strip()
    if not slug:
        return ""
    prefix = (os.environ.get("COUPANG_SUB_ID_PREFIX") or "").strip() or "shop"
    return f"{prefix}_{slug}"


def coupang_sub_id_for_channel(
    channel: dict,
    *,
    db: Session | None,
) -> str:
    """파트너스 리포트용 subId. `{CHANNEL_*_COUPANG_SUB_ID_PREFIX}_{공개몰슬러그}` (예: `af201_soccer`)."""
    cid = (channel.get("channel_id") or "").strip() or "unknown"
    prefix = coupang_sub_id_prefix(cid)
    inf = influencer_for_channel(db, channel) if db is not None else None
    slug = shop_public_path_slug(inf, channel)
    if not slug:
        slug = cid
    return f"{prefix}_{slug}"


def mall_shop_url_for_channel(
    channel: dict,
    *,
    db: Session | None,
    request: Request | None = None,
) -> str:
    """이 채널에 대응하는 공개 몰 상점 URL(비어 있을 수 있음)."""
    origin = public_site_origin(request=request)
    inf = influencer_for_channel(db, channel) if db is not None else None
    slug = shop_public_path_slug(inf, channel)
    return public_shop_page_url(origin=origin, shop_path_slug=slug)
