"""안지아픽 — 보안 인플루언서. channel_id·env 접두어 `105` — `.env` 의 `CHANNEL_105_*`.

홈캠카오스(지식쇼츠, short-mall) 와 세트. 영상 주제 기반 쿠팡 큐레이션 상품을 이 몰(/safety)에 적재한다.
상품 공급원(시트/큐레이션)이 비어 있으면 빈 몰로 동작한다.
"""
from __future__ import annotations

import os

from ..constants import COMMON_HISTORY_FILE_ID, NAVER_CATEGORY_IDS
from ..env_names import channel_env

_CID = "105"


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
        "name": "안지아픽(보안인플루언서)",
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
        # 비우면 어드민·쇼츠 매칭에서 채널을 못 찾음 → DB 인플 slug `safety` 와 동일하게 둔다.
        "mall_influencer_slug": (
            os.getenv(channel_env(_CID, "MALL_INFLUENCER_SLUG"), "").strip() or "safety"
        ),
        "naver_category_id": [
            NAVER_CATEGORY_IDS["디지털/가전"],
            NAVER_CATEGORY_IDS["생활/건강"],
        ],
        "trend_keywords": [
            "홈캠",
            "CCTV",
            "스마트도어락",
            "도어락",
            "블랙박스",
            "현관문보안",
            "지문인식",
            "보안",
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
