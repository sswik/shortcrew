"""채널 공통 상수.

`.env` 는 애플리케이션 진입점(`main.py`)에서 한 번만 로드한다.
"""
from __future__ import annotations

import os

COMMON_HISTORY_FILE_ID = os.getenv("COMMON_HISTORY_FILE_ID", "")

NAVER_CATEGORY_IDS: dict[str, str] = {
    "패션의류": "50000000",
    "화장품/미용": "50000002",
    "디지털/가전": "50000167",
    "식품": "50000169",
    "가구/인테리어": "50000170",
    "출산/육아": "50000171",
    "스포츠/레저": "50000172",
    "생활/건강": "50000173",
    "패션잡화": "50000174",
    "도서": "50000175",
}

DEFAULT_TREND_KEYWORDS: list[str] = [
    "스킨케어",
    "립스틱",
    "클렌징",
    "선크림",
    "마스크팩",
    "자취꿀템",
    "주방용품",
    "생필품",
    "가성비",
    "쿠팡추천",
]
