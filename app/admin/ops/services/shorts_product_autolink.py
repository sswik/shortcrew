"""쇼츠 자동 발행용 상품탭 upsert + DB products 동기화."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.ops.services.google_sheets import append_rows, get_all_rows
from app.admin.ops.services.shorts_name_normalize import names_equivalent
from models import Product


def _cell(row: list[Any], col_idx: int) -> str:
    if col_idx < 0 or col_idx >= len(row):
        return ""
    v = row[col_idx]
    if v is None:
        return ""
    return str(v).strip()


async def upsert_product_row_in_sheet(
    *,
    spreadsheet_id: str,
    product_tab: str,
    product_range: str,
    product_name: str,
    product_url: str,
    deep_link: str,
    price: str,
    image_url: str,
    channel_id: str,
    product_name_col: int,
    product_deeplink_col: int,
    product_status_col: int,
    product_status_value: str,
) -> str:
    """상품탭에 상품명 기준 upsert. 기존 있으면 딥링크 재사용, 없으면 신규 append."""
    rows = await get_all_rows(spreadsheet_id, product_tab, product_range)
    for row in rows[1:]:
        pname = _cell(row, product_name_col)
        if not pname:
            continue
        if not names_equivalent(pname, product_name):
            continue
        exist_dl = _cell(row, product_deeplink_col)
        if exist_dl:
            return exist_dl
        break

    status = product_status_value or "게시중"
    now_ymd = datetime.now().strftime("%Y-%m-%d")
    row = [
        "=ROW()-1",  # A No
        "",  # B category
        product_name,  # C
        price or "0",  # D
        image_url or "",  # E
        product_url or "",  # F
        deep_link or "",  # G
        "",  # H videoNo
        status,  # I
        now_ymd,  # J
        "",  # K
    ]
    await append_rows(
        spreadsheet_id=spreadsheet_id,
        sheet_tab_name=product_tab,
        rows=[row],
        column_range="A:K",
    )
    return deep_link or ""


def upsert_product_in_db(
    *,
    db: Session,
    influencer_slug: str,
    product_name: str,
    product_url: str,
    price: str,
    image_url: str,
) -> Product:
    """DB products 테이블에 상품명 기준 upsert."""
    products = db.scalars(
        select(Product).where(func.lower(Product.influencer_slug) == influencer_slug.lower())
    ).all()
    for p in products:
        if names_equivalent(p.title, product_name):
            if product_url and (not p.coupang_url or not p.coupang_url.strip()):
                p.coupang_url = product_url
            if image_url and (not p.image_url or not p.image_url.strip()):
                p.image_url = image_url
            try:
                if price:
                    p.price = float(str(price).replace(",", ""))
            except Exception:
                pass
            db.commit()
            db.refresh(p)
            return p

    parsed_price = 0.0
    try:
        if price:
            parsed_price = float(str(price).replace(",", ""))
    except Exception:
        parsed_price = 0.0
    new_p = Product(
        influencer_slug=influencer_slug,
        title=product_name[:255],
        price=parsed_price,
        image_url=(image_url or "")[:500],
        coupang_url=(product_url or "")[:500],
    )
    db.add(new_p)
    db.commit()
    db.refresh(new_p)
    return new_p
