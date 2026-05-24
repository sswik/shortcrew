"""레거시: 시트 행을 SQLite `products`에 넣는 동기화(공개 몰은 시트 JSON API만 사용하므로 현재 라우트에서 호출하지 않음)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from models import Influencer, Product, SessionLocal

logger = logging.getLogger(__name__)

_SHEET_ITEM_KEYS = [
    "no",
    "category",
    "productName",
    "price",
    "imageUrl",
    "productUrl",
    "deepLink",
    "videoNo",
    "status",
    "regDate",
    "subId",
]


def sheet_rows_to_product_payloads(rows: list[list[Any]]) -> list[dict[str, Any]]:
    """시트 A:K 원시 행(0행 헤더)을 `sync_sent_products_to_db`용 dict 목록으로 변환."""
    payloads: list[dict[str, Any]] = []
    for index in range(1, len(rows)):
        row = rows[index]
        if not isinstance(row, list):
            continue
        padded = (row + [""] * 11)[:11]
        item: dict[str, Any] = {}
        for i, key in enumerate(_SHEET_ITEM_KEYS):
            val = padded[i] if i < len(padded) else ""
            item[key] = "" if val is None else str(val).strip() if isinstance(val, str) else val
        payloads.append(
            {
                "productName": item.get("productName") or "",
                "price": item.get("price"),
                "imageUrl": item.get("imageUrl") or "",
                "productUrl": item.get("productUrl") or "",
                "deepLink": item.get("deepLink") or "",
            }
        )
    return payloads


def sync_sent_products_to_db(influencer_slug: str, products: list[dict[str, Any]]) -> tuple[int, str | None]:
    """전송 확정 상품을 DB에 추가한다. 이미 같은 쿠팡 URL이 있으면 건너뜀.

    Returns:
        (추가된 행 수, 경고 문구 또는 None)
    """
    slug = (influencer_slug or "").strip()
    if not slug:
        return 0, None
    if not products:
        return 0, None

    db = SessionLocal()
    try:
        inf = db.scalar(select(Influencer).where(Influencer.name_slug == slug))
        if inf is None:
            msg = f"인플루언서 name_slug={slug!r} 가 DB에 없어 몰 동기화를 건너뜁니다."
            logger.warning(msg)
            return 0, msg

        inserted = 0
        for p in products:
            if not isinstance(p, dict):
                continue
            deep = (str(p.get("deepLink") or "")).strip()
            plain = (str(p.get("productUrl") or "")).strip()
            coupang_url = (deep or plain)[:500]
            if not coupang_url:
                continue
            title = (str(p.get("productName") or "")).strip()[:255]
            if not title:
                continue
            try:
                price = float(p.get("price") or 0)
            except (TypeError, ValueError):
                price = 0.0
            image_url = (str(p.get("imageUrl") or "")).strip()[:500]

            url_keys = {coupang_url}
            if plain:
                url_keys.add(plain[:500])
            if deep:
                url_keys.add(deep[:500])
            url_keys.discard("")
            dup = db.scalar(select(Product.id).where(Product.coupang_url.in_(list(url_keys))))
            if dup is not None:
                continue

            db.add(
                Product(
                    influencer_slug=slug,
                    title=title,
                    price=price,
                    image_url=image_url or "",
                    coupang_url=coupang_url,
                )
            )
            inserted += 1
        db.commit()
        return inserted, None
    except Exception:
        db.rollback()
        logger.exception("mall_product_sync_failed slug=%s", slug)
        return 0, "몰 DB 동기화 중 오류가 발생했습니다. 시트 전송은 완료되었습니다."
    finally:
        db.close()
