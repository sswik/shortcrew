"""한소율픽 — 쇼핑 인플루언서. `roster/shopping.py`. channel_id·env 접두어 `104` — `.env` 의 `CHANNEL_104_*`."""
from __future__ import annotations

import os

from ..constants import COMMON_HISTORY_FILE_ID, NAVER_CATEGORY_IDS
from ..env_names import channel_env

_CID = "104"


def _env_truthy(key: str) -> bool:
    return (os.getenv(key) or "").strip().lower() in ("1", "true", "yes", "on")


def build() -> dict:
    """채널 1건 dict. 키 스키마는 `registry.py` 상단 주석과 동일해야 함."""
    product_delivery = os.getenv(
        channel_env(_CID, "PRODUCT_DELIVERY_WEBAPP_URL"),
        "",
    ).strip()
    mall_products = os.getenv(
        channel_env(_CID, "MALL_PRODUCTS_API_URL"),
        "",
    ).strip()
    tab_default = os.getenv(channel_env(_CID, "TAB"), "상품목록").strip() or "상품목록"
    return {
        "channel_id": _CID,
        "name": "한소율픽(쇼핑인플루언서)",
        "google_sheet_id": os.getenv(channel_env(_CID, "FILE_ID"), "").strip(),
        "sheet_tab_name": tab_default,
        "history_sheet_id": COMMON_HISTORY_FILE_ID,
        "history_sheet_tab": os.getenv(channel_env(_CID, "HISTORY_TAB"), "기록").strip() or "기록",
        "product_delivery_url": product_delivery,
        "mall_products_api_url": mall_products or product_delivery,
        "mall_products_channel_param": os.getenv(
            channel_env(_CID, "MALL_PRODUCTS_CHANNEL_PARAM"),
            "",
        ).strip(),
        # 비우면 어드민·쇼츠 매칭에서 채널을 못 찾음 → DB 인플 slug `shopping` 과 동일하게 둔다.
        "mall_influencer_slug": (
            os.getenv(channel_env(_CID, "MALL_INFLUENCER_SLUG"), "").strip() or "shopping"
        ),
        "naver_category_id": [
            NAVER_CATEGORY_IDS["생활/건강"],
            NAVER_CATEGORY_IDS["패션의류"],
            NAVER_CATEGORY_IDS["화장품/미용"],
        ],
        "trend_keywords": [
            "라이브커머스",
            "데일리템",
            "자취꿀템",
            "주방용품",
            "생필품",
            "스킨케어",
            "가성비",
            "쿠팡추천",
        ],
        "monitor_keywords": [],
        # --- 쇼츠 시트 트리거 리뷰 자동화 (06.운영가이드/06_쇼츠시트리뷰자동화.md 참고) ---
        "shorts_automation_enabled": _env_truthy(channel_env(_CID, "SHORTS_AUTOMATION_ENABLED")),
        "shorts_plan_tab": os.getenv(channel_env(_CID, "SHORTS_PLAN_TAB"), "").strip(),
        "shorts_product_tab": os.getenv(channel_env(_CID, "SHORTS_PRODUCT_TAB"), "").strip(),
        "shorts_plan_range": os.getenv(channel_env(_CID, "SHORTS_PLAN_RANGE"), "A:W").strip() or "A:W",
        "shorts_product_range": os.getenv(channel_env(_CID, "SHORTS_PRODUCT_RANGE"), "A:K").strip() or "A:K",
        "shorts_plan_status_value": os.getenv(channel_env(_CID, "SHORTS_PLAN_STATUS_VALUE"), "완료").strip()
        or "완료",
        "shorts_product_status_value": os.getenv(
            channel_env(_CID, "SHORTS_PRODUCT_STATUS_VALUE"), "게시중"
        ).strip()
        or "게시중",
        "shorts_col_plan_status": os.getenv(channel_env(_CID, "SHORTS_COL_PLAN_STATUS"), "C").strip() or "C",
        "shorts_col_plan_date": os.getenv(channel_env(_CID, "SHORTS_COL_PLAN_DATE"), "D").strip() or "D",
        "shorts_plan_date_tz": os.getenv(channel_env(_CID, "SHORTS_PLAN_DATE_TZ"), "Asia/Seoul").strip()
        or "Asia/Seoul",
        "shorts_col_plan_youtube": os.getenv(channel_env(_CID, "SHORTS_COL_PLAN_YOUTUBE"), "W").strip() or "W",
        "shorts_col_plan_product": os.getenv(channel_env(_CID, "SHORTS_COL_PLAN_PRODUCT"), "F").strip() or "F",
        "shorts_col_product_status": os.getenv(channel_env(_CID, "SHORTS_COL_PRODUCT_STATUS"), "I").strip()
        or "I",
        "shorts_col_product_name": os.getenv(channel_env(_CID, "SHORTS_COL_PRODUCT_NAME"), "C").strip() or "C",
        "shorts_col_product_deeplink": os.getenv(channel_env(_CID, "SHORTS_COL_PRODUCT_DEEPLINK"), "G").strip()
        or "G",
    }
