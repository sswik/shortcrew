"""운영 채널 목록.

채널별 `build()` 는 `roster/` 아래 모듈에 두고, `registry.py`의 `CHANNEL_BUILDERS`에
등록한다.

API·라우트에서는 **`get_channels()`** 를 쓴다. 매 호출마다 `os.environ`(`.env` 반영)을
다시 읽어 시트 ID 등이 최신으로 잡힌다. 모듈 최초 import 시점만 쓰면 `.env`가 비어 있어
빈 설정이 고정되는 문제가 생길 수 있다.

외부 import 예:

    from app.admin.ops.channels import get_channels, NAVER_CATEGORY_IDS, DEFAULT_TREND_KEYWORDS
"""
from __future__ import annotations

from .constants import COMMON_HISTORY_FILE_ID, DEFAULT_TREND_KEYWORDS, NAVER_CATEGORY_IDS
from .registry import CHANNEL_BUILDERS


def get_channels() -> list[dict]:
    """채널 dict 목록을 매번 새로 만든다 (`build()` 안의 os.getenv 가 현재 환경을 본다)."""
    return [builder() for builder in CHANNEL_BUILDERS]


CHANNELS: list[dict] = get_channels()

__all__ = [
    "CHANNELS",
    "CHANNEL_BUILDERS",
    "get_channels",
    "COMMON_HISTORY_FILE_ID",
    "DEFAULT_TREND_KEYWORDS",
    "NAVER_CATEGORY_IDS",
]
