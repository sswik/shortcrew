"""수동 리뷰 에디터용 상품 매칭 헬퍼.

(구) 쇼츠 시트 자동발행 파이프라인은 폐기됨. 자동발행은 브리지 큐레이션
(`app/admin/ops/routes/bridge.py`)으로 대체. 이 파일은 어드민 리뷰 폼이
시트 상품명으로 DB 상품을 찾을 때만 쓰인다.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.ops.services.shorts_name_normalize import names_equivalent
from models import Product


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
