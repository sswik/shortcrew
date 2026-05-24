"""어드민 리뷰 폼: 구글 시트 상품 탭에서 '게시중'인 행의 상품명·딥링크와 DB products 매칭."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.ops.channels import get_channels
from app.admin.ops.services.google_sheets import get_all_rows, get_spreadsheet_sheet_titles
from app.admin.ops.services.review_publish_service import find_product_for_sheet_product_name
from app.admin.ops.services.shorts_name_normalize import names_equivalent
from app.admin.ops.services.shorts_review_config import column_letters_to_index
from models import Product

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReviewFormProductOption:
    """셀렉트 한 줄: DB id·표시 제목·시트(또는 DB) 딥링크."""

    id: int
    title: str
    deeplink: str
    sheet_title: str | None = None


def _col_letter(channel: dict, roster_key: str, default_letter: str) -> int:
    raw = (channel.get(roster_key) or "").strip() or default_letter
    return column_letters_to_index(raw)


def _channel_for_influencer_slug(influencer_slug: str) -> dict | None:
    want = (influencer_slug or "").strip().lower()
    if not want:
        return None
    for ch in get_channels():
        mall = (ch.get("mall_influencer_slug") or "").strip().lower()
        if mall == want:
            return ch
    return None


async def _resolve_product_sheet_tab(ch: dict, spreadsheet_id: str) -> str:
    """몰 상품 탭(`sheet_tab_name` = ``CHANNEL_<ID>_TAB``) 우선, 없으면 ``SHORTS_PRODUCT_TAB``, 둘 다 없으면 2번째 탭."""
    tab = (ch.get("sheet_tab_name") or "").strip() or (ch.get("shorts_product_tab") or "").strip()
    if tab:
        return tab
    try:
        titles = await get_spreadsheet_sheet_titles(spreadsheet_id)
    except Exception:
        logger.exception("admin_review_products list_sheet_titles failed")
        return ""
    if len(titles) >= 2:
        return titles[1]
    return titles[0] if titles else ""


def _cell(row: list[Any], col_idx: int) -> str:
    if col_idx < 0 or col_idx >= len(row):
        return ""
    v = row[col_idx]
    if v is None:
        return ""
    return str(v).strip()


def _options_from_products(products: list[Product]) -> list[ReviewFormProductOption]:
    out: list[ReviewFormProductOption] = []
    for p in products:
        dl = (p.coupang_url or "").strip()
        out.append(ReviewFormProductOption(id=p.id, title=p.title, deeplink=dl, sheet_title=None))
    return out


def _fallback_options(db: Session, influencer_slug: str) -> list[ReviewFormProductOption]:
    slug = (influencer_slug or "").strip().lower()
    if not slug:
        return []
    prods = list(
        db.scalars(
            select(Product)
            .where(func.lower(Product.influencer_slug) == slug)
            .order_by(Product.title)
        ).all()
    )
    return _options_from_products(prods)


async def product_options_from_sheet_published(
    db: Session,
    influencer_slug: str,
    *,
    ensure_product_id: int | None = None,
) -> list[ReviewFormProductOption]:
    """시트 ``게시중`` 행의 상품명(C)·딥링크(G)로 DB 상품 매칭, 시트 순서 유지."""
    ch = _channel_for_influencer_slug(influencer_slug)
    sid = (ch.get("google_sheet_id") or "").strip() if ch else ""

    if not ch or not sid:
        logger.warning(
            "admin_review_products no_channel_or_file_id slug=%s ch_found=%s",
            influencer_slug,
            ch is not None,
        )
        return _fallback_options(db, influencer_slug)

    tab = await _resolve_product_sheet_tab(ch, sid)
    if not tab:
        logger.warning(
            "admin_review_products empty_product_tab slug=%s file_id_prefix=%s",
            influencer_slug,
            sid[:10],
        )
        return _fallback_options(db, influencer_slug)

    logger.info(
        "admin_review_products sheet slug=%s product_tab=%r",
        influencer_slug,
        tab,
    )

    rng = (ch.get("shorts_product_range") or "A:K").strip() or "A:K"
    status_col = _col_letter(ch, "shorts_col_product_status", "I")
    name_col = _col_letter(ch, "shorts_col_product_name", "C")
    deeplink_col = _col_letter(ch, "shorts_col_product_deeplink", "G")
    status_val = (ch.get("shorts_product_status_value") or "게시중").strip() or "게시중"

    try:
        rows = await get_all_rows(sid, tab, rng)
    except Exception:
        logger.exception(
            "admin_review_products sheet read failed slug=%s tab=%r",
            influencer_slug,
            tab,
        )
        return _fallback_options(db, influencer_slug)

    ordered: list[ReviewFormProductOption] = []
    seen_positive: set[int] = set()
    status_hit = 0
    sheet_only_keys: set[str] = set()

    for i in range(1, len(rows)):
        row = rows[i]
        if _cell(row, status_col) != status_val:
            continue
        status_hit += 1
        pname = _cell(row, name_col)
        sheet_dl = _cell(row, deeplink_col).strip()
        if not pname or not sheet_dl:
            continue

        p = find_product_for_sheet_product_name(db, influencer_slug, pname)
        if p is not None:
            if p.id in seen_positive:
                continue
            seen_positive.add(p.id)
            dl = sheet_dl or (p.coupang_url or "").strip()
            ordered.append(
                ReviewFormProductOption(id=p.id, title=p.title, deeplink=dl, sheet_title=None)
            )
            continue

        pname_clean = pname.strip()
        key = pname_clean.casefold()
        if key in sheet_only_keys:
            continue
        if any(
            names_equivalent(pname_clean, o.title)
            for o in ordered
            if o.id > 0
        ):
            continue
        sheet_only_keys.add(key)
        neg_id = -(200_000 + i)
        ordered.append(
            ReviewFormProductOption(
                id=neg_id,
                title=pname_clean,
                deeplink=sheet_dl,
                sheet_title=pname_clean,
            )
        )

    if ensure_product_id is not None:
        pid = int(ensure_product_id)
        have = {o.id for o in ordered}
        if pid > 0 and pid not in have:
            extra = db.scalar(
                select(Product).where(
                    Product.id == pid,
                    func.lower(Product.influencer_slug) == (influencer_slug or "").strip().lower(),
                )
            )
            if extra is not None:
                dl = (extra.coupang_url or "").strip()
                ordered.append(
                    ReviewFormProductOption(
                        id=extra.id, title=extra.title, deeplink=dl, sheet_title=None
                    )
                )

    if not ordered:
        fb = _fallback_options(db, influencer_slug)
        logger.warning(
            "admin_review_products no_sheet_rows slug=%s tab=%r status=%r "
            "게시중_row_count=%s data_rows=%s fallback_count=%s",
            influencer_slug,
            tab,
            status_val,
            status_hit,
            max(0, len(rows) - 1),
            len(fb),
        )
        return fb

    db_matched = sum(1 for o in ordered if o.id > 0)
    sheet_only = sum(1 for o in ordered if o.id < 0)
    logger.info(
        "admin_review_products options slug=%s tab=%r total=%s db_matched=%s sheet_only=%s",
        influencer_slug,
        tab,
        len(ordered),
        db_matched,
        sheet_only,
    )

    return ordered


def merge_saved_sheet_option_into_product_list(
    products: list[ReviewFormProductOption],
    *,
    review_product_id: int,
    review_id: int,
    review_sheet_title: str,
    review_sheet_deeplink: str,
) -> tuple[list[ReviewFormProductOption], int | None]:
    """수정 폼: ``product_id`` 없이 시트만 저장된 리뷰면 목록에 한 줄 보강·선택 id 반환."""
    if review_product_id:
        return products, None
    st = (review_sheet_title or "").strip()
    sd = (review_sheet_deeplink or "").strip()
    if not st and not sd:
        return products, None
    for p in products:
        if p.id < 0 and (p.deeplink or "").strip() == sd and sd:
            return products, p.id
    sid = -(300_000 + review_id)
    head = ReviewFormProductOption(
        id=sid,
        title=st or sd,
        deeplink=sd,
        sheet_title=st or None,
    )
    return [head, *list(products)], sid


def load_review_form_products(
    db: Session,
    influencer_slug: str,
    *,
    ensure_product_id: int | None = None,
) -> list[ReviewFormProductOption]:
    slug = (influencer_slug or "").strip()
    try:
        return asyncio.run(
            product_options_from_sheet_published(
                db, slug, ensure_product_id=ensure_product_id
            )
        )
    except Exception:
        logger.exception("admin_review_products failed slug=%s", slug)
        return _fallback_options(db, slug)
