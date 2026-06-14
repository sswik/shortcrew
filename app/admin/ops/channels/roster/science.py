"""정세윤픽(테크인플루언서) — channel_id·env 접두어 `107` — `.env` 의 `CHANNEL_107_*`. 큐레이션 인플루언서(세트)."""
from __future__ import annotations

import os

from ..constants import COMMON_HISTORY_FILE_ID, NAVER_CATEGORY_IDS
from ..env_names import channel_env

_CID = "107"


def _env_truthy(key: str) -> bool:
    return (os.getenv(key) or "").strip().lower() in ("1", "true", "yes", "on")


def build() -> dict:
    product_delivery = os.getenv(channel_env(_CID, "PRODUCT_DELIVERY_WEBAPP_URL"), "").strip()
    mall_products = os.getenv(channel_env(_CID, "MALL_PRODUCTS_API_URL"), "").strip()
    return {
        "channel_id": _CID,
        "name": "정세윤픽(테크인플루언서)",
        "google_sheet_id": os.getenv(channel_env(_CID, "FILE_ID"), "").strip(),
        "sheet_tab_name": os.getenv(channel_env(_CID, "TAB"), "상품목록").strip() or "상품목록",
        "history_sheet_id": COMMON_HISTORY_FILE_ID,
        "history_sheet_tab": os.getenv(channel_env(_CID, "HISTORY_TAB"), "기록").strip() or "기록",
        "product_delivery_url": product_delivery,
        "mall_products_api_url": mall_products or product_delivery,
        "mall_products_channel_param": os.getenv(channel_env(_CID, "MALL_PRODUCTS_CHANNEL_PARAM"), "").strip(),
        "mall_influencer_slug": (os.getenv(channel_env(_CID, "MALL_INFLUENCER_SLUG"), "").strip() or "science"),
        "naver_category_id": [
            NAVER_CATEGORY_IDS["디지털/가전"],
            NAVER_CATEGORY_IDS["생활/건강"],
        ],
        "trend_keywords": [
            "데스크셋업",
            "기계식키보드",
            "무선마우스",
            "모니터암",
            "USB허브",
            "멀티탭",
            "스마트가젯",
            "책상정리",
            "가성비",
        ],
        "monitor_keywords": [],
        "shorts_automation_enabled": _env_truthy(channel_env(_CID, "SHORTS_AUTOMATION_ENABLED")),
        "shorts_plan_tab": os.getenv(channel_env(_CID, "SHORTS_PLAN_TAB"), "").strip(),
        "shorts_product_tab": os.getenv(channel_env(_CID, "SHORTS_PRODUCT_TAB"), "").strip(),
        "shorts_plan_range": os.getenv(channel_env(_CID, "SHORTS_PLAN_RANGE"), "A:W").strip() or "A:W",
        "shorts_product_range": os.getenv(channel_env(_CID, "SHORTS_PRODUCT_RANGE"), "A:K").strip() or "A:K",
        "shorts_plan_status_value": os.getenv(channel_env(_CID, "SHORTS_PLAN_STATUS_VALUE"), "완료").strip() or "완료",
        "shorts_product_status_value": os.getenv(channel_env(_CID, "SHORTS_PRODUCT_STATUS_VALUE"), "게시중").strip() or "게시중",
        "shorts_col_plan_status": os.getenv(channel_env(_CID, "SHORTS_COL_PLAN_STATUS"), "C").strip() or "C",
        "shorts_col_plan_date": os.getenv(channel_env(_CID, "SHORTS_COL_PLAN_DATE"), "D").strip() or "D",
        "shorts_plan_date_tz": os.getenv(channel_env(_CID, "SHORTS_PLAN_DATE_TZ"), "Asia/Seoul").strip() or "Asia/Seoul",
        "shorts_col_plan_youtube": os.getenv(channel_env(_CID, "SHORTS_COL_PLAN_YOUTUBE"), "W").strip() or "W",
        "shorts_col_plan_product": os.getenv(channel_env(_CID, "SHORTS_COL_PLAN_PRODUCT"), "F").strip() or "F",
        "shorts_col_product_status": os.getenv(channel_env(_CID, "SHORTS_COL_PRODUCT_STATUS"), "I").strip() or "I",
        "shorts_col_product_name": os.getenv(channel_env(_CID, "SHORTS_COL_PRODUCT_NAME"), "C").strip() or "C",
        "shorts_col_product_deeplink": os.getenv(channel_env(_CID, "SHORTS_COL_PRODUCT_DEEPLINK"), "G").strip() or "G",
        "shorts_auto_product_fallback_enabled": _env_truthy(channel_env(_CID, "SHORTS_AUTO_PRODUCT_FALLBACK_ENABLED")),
        "shorts_auto_product_search_limit": int((os.getenv(channel_env(_CID, "SHORTS_AUTO_PRODUCT_SEARCH_LIMIT"), "5").strip() or "5")),
    }
