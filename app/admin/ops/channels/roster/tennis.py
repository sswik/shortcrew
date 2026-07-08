"""왕세림픽 — 테니스 인플루언서. `roster/tennis.py`. channel_id·env 접두어 `103` — `.env` 의 `CHANNEL_103_*`."""
from __future__ import annotations

import os

from ..constants import COMMON_HISTORY_FILE_ID, NAVER_CATEGORY_IDS
from ..env_names import channel_env

_CID = "303"


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
    return {
        "channel_id": _CID,
        "name": "왕세림픽(테니스인플루언서)",
        "google_sheet_id": os.getenv(channel_env(_CID, "FILE_ID"), "").strip(),
        "sheet_tab_name": os.getenv(channel_env(_CID, "TAB"), "상품목록").strip() or "상품목록",
        "history_sheet_id": COMMON_HISTORY_FILE_ID,
        "history_sheet_tab": os.getenv(channel_env(_CID, "HISTORY_TAB"), "기록").strip() or "기록",
        "product_delivery_url": product_delivery,
        "mall_products_api_url": mall_products or product_delivery,
        "mall_products_channel_param": os.getenv(
            channel_env(_CID, "MALL_PRODUCTS_CHANNEL_PARAM"),
            "",
        ).strip(),
        "mall_influencer_slug": os.getenv(
            channel_env(_CID, "MALL_INFLUENCER_SLUG"),
            "",
        ).strip(),
        "naver_category_id": [
            NAVER_CATEGORY_IDS["스포츠/레저"],
            NAVER_CATEGORY_IDS["패션의류"],
        ],
        "trend_keywords": [
            "테니스",
            "테니스화",
            "테니스라켓",
            "테니스복",
            "운동화",
            "스포츠양말",
            "그립테이프",
            "캡",
            "가성비",
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
        # --- 쇼츠 자동 상품 보강 ---
        "shorts_auto_product_fallback_enabled": _env_truthy(
            channel_env(_CID, "SHORTS_AUTO_PRODUCT_FALLBACK_ENABLED")
        ),
        "shorts_auto_product_search_limit": int(
            (os.getenv(channel_env(_CID, "SHORTS_AUTO_PRODUCT_SEARCH_LIMIT"), "5").strip() or "5")
        ),
    }
