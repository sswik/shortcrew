"""
신규 채널 roster 복사용 템플릿 (channel_id 는 `01`, `201` 등 숫자 문자열 권장).

1. 이 파일을 `channel_202.py` 처럼 **새 파일명**으로 복사한다.
2. 아래 `_CHANNEL_ID` 와 `name`, `naver_category_id`, `trend_keywords` 등을 채운다.
3. `registry.py` 에서 `from .roster import channel_202` 후 `CHANNEL_BUILDERS` 튜플에 `channel_202.build` 를 추가한다.
4. `.env` 키는 `CHANNEL_{channel_id}_*` (예: id 가 `202` → `CHANNEL_202_FILE_ID`, `CHANNEL_202_PRODUCT_DELIVERY_WEBAPP_URL`; 몰 GET URL은 선택 `CHANNEL_202_MALL_PRODUCTS_API_URL`).
5. 쇼츠 시트 트리거 리뷰 자동화를 쓰려면 `roster/shopping.py` 와 동일한 `shorts_*` 키를 `build()` 에 넣고 `CHANNEL_*_SHORTS_*` env 를 채운다. (`docs/06_SHORTS_SHEET_REVIEWS.md`)

이 모듈은 `CHANNEL_BUILDERS` 에 **등록하지 않는다**.
"""
from __future__ import annotations

import os

from ..constants import COMMON_HISTORY_FILE_ID, NAVER_CATEGORY_IDS
from ..env_names import channel_env

_CHANNEL_ID = "202"  # TODO: 실제 번호로 변경 (예: 01, 102, 201)


def build() -> dict:
    cid = _CHANNEL_ID
    product_delivery = os.getenv(
        channel_env(cid, "PRODUCT_DELIVERY_WEBAPP_URL"),
        "",
    ).strip()
    mall_products = os.getenv(
        channel_env(cid, "MALL_PRODUCTS_API_URL"),
        "",
    ).strip()
    return {
        "channel_id": cid,
        "name": "○○○픽(분야명)",
        "google_sheet_id": os.getenv(channel_env(cid, "FILE_ID"), "").strip(),
        "sheet_tab_name": os.getenv(channel_env(cid, "TAB"), "상품목록").strip() or "상품목록",
        "history_sheet_id": COMMON_HISTORY_FILE_ID,
        "history_sheet_tab": os.getenv(channel_env(cid, "HISTORY_TAB"), "기록").strip() or "기록",
        "product_delivery_url": product_delivery,
        "mall_products_api_url": mall_products or product_delivery,
        "mall_products_channel_param": os.getenv(
            channel_env(cid, "MALL_PRODUCTS_CHANNEL_PARAM"),
            "",
        ).strip(),
        "mall_influencer_slug": os.getenv(
            channel_env(cid, "MALL_INFLUENCER_SLUG"),
            "",
        ).strip(),
        "naver_category_id": [
            NAVER_CATEGORY_IDS["스포츠/레저"],
        ],
        "trend_keywords": [],
        "monitor_keywords": [],
        # 쇼츠 리뷰 자동화: shopping.py 참고해 동일 키·env 를 복사해 켠다. 기본은 끔.
        "shorts_automation_enabled": False,
        "shorts_plan_tab": "",
        "shorts_product_tab": "",
        "shorts_plan_range": "A:W",
        "shorts_product_range": "A:K",
        "shorts_plan_status_value": "완료",
        "shorts_product_status_value": "게시중",
        "shorts_col_plan_status": "C",
        "shorts_col_plan_date": "D",
        "shorts_plan_date_tz": "Asia/Seoul",
        "shorts_col_plan_youtube": "W",
        "shorts_col_plan_product": "F",
        "shorts_col_product_status": "I",
        "shorts_col_product_name": "C",
        "shorts_col_product_deeplink": "G",
    }
