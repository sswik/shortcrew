"""쇼츠 시트 트리거 리뷰 자동화 — 채널별 설정(로스터 dict + env)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.admin.ops.channels import get_channels


def column_letters_to_index(letters: str) -> int:
    """엑셀 열 문자 → 0기반 인덱스 (A=0, Z=25, AA=26)."""
    s = (letters or "").strip().upper()
    if not s:
        raise ValueError("empty column")
    n = 0
    for ch in s:
        if ch < "A" or ch > "Z":
            raise ValueError(f"invalid column letter: {letters!r}")
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def _col_letter(channel: dict, roster_key: str, default_letter: str) -> int:
    raw = (channel.get(roster_key) or "").strip() or default_letter
    return column_letters_to_index(raw)


@dataclass(frozen=True)
class ShortsReviewConfig:
    """시트 Match Maker + 파이프라인에 필요한 채널 단위 설정."""

    channel_id: str
    spreadsheet_id: str
    mall_influencer_slug: str
    plan_tab: str
    product_tab: str
    plan_range: str
    product_range: str
    plan_status_col: int
    plan_date_col: int
    plan_date_tz: str
    plan_youtube_col: int
    plan_product_col: int
    plan_status_value: str
    product_status_col: int
    product_name_col: int
    product_deeplink_col: int
    product_status_value: str


def today_for_shorts_plan_sheet(cfg: ShortsReviewConfig) -> date:
    """기획 탭 D열 등과 비교할 '오늘' 날짜 (IANA 타임존, 기본 Asia/Seoul)."""
    tz_name = (cfg.plan_date_tz or "Asia/Seoul").strip() or "Asia/Seoul"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Seoul")
    return datetime.now(tz).date()


def shorts_config_from_channel(channel: dict) -> ShortsReviewConfig | None:
    """채널 dict에서 설정을 만든다. 자동화 비활성·필수 값 누락 시 None."""
    if not channel.get("shorts_automation_enabled"):
        return None
    sid = (channel.get("google_sheet_id") or "").strip()
    if not sid:
        return None
    plan_tab = (channel.get("shorts_plan_tab") or "").strip()
    if not plan_tab:
        return None
    product_tab = (channel.get("shorts_product_tab") or "").strip()
    if not product_tab:
        product_tab = (channel.get("sheet_tab_name") or "상품목록").strip() or "상품목록"
    cid = (channel.get("channel_id") or "").strip()
    mall = (channel.get("mall_influencer_slug") or "").strip()
    if not cid or not mall:
        return None

    plan_range = (channel.get("shorts_plan_range") or "A:W").strip() or "A:W"
    product_range = (channel.get("shorts_product_range") or "A:K").strip() or "A:K"
    plan_status_val = (channel.get("shorts_plan_status_value") or "완료").strip() or "완료"
    product_status_val = (channel.get("shorts_product_status_value") or "게시중").strip() or "게시중"

    plan_date_tz = (channel.get("shorts_plan_date_tz") or "Asia/Seoul").strip() or "Asia/Seoul"

    return ShortsReviewConfig(
        channel_id=cid,
        spreadsheet_id=sid,
        mall_influencer_slug=mall,
        plan_tab=plan_tab,
        product_tab=product_tab,
        plan_range=plan_range,
        product_range=product_range,
        plan_status_col=_col_letter(channel, "shorts_col_plan_status", "C"),
        plan_date_col=_col_letter(channel, "shorts_col_plan_date", "D"),
        plan_date_tz=plan_date_tz,
        plan_youtube_col=_col_letter(channel, "shorts_col_plan_youtube", "W"),
        plan_product_col=_col_letter(channel, "shorts_col_plan_product", "F"),
        plan_status_value=plan_status_val,
        product_status_col=_col_letter(channel, "shorts_col_product_status", "I"),
        product_name_col=_col_letter(channel, "shorts_col_product_name", "C"),
        product_deeplink_col=_col_letter(channel, "shorts_col_product_deeplink", "G"),
        product_status_value=product_status_val,
    )


def iter_shorts_review_configs() -> list[ShortsReviewConfig]:
    """로스터 전 채널 중 쇼츠 자동화가 켜진 것만."""
    out: list[ShortsReviewConfig] = []
    for ch in get_channels():
        cfg = shorts_config_from_channel(ch)
        if cfg is not None:
            out.append(cfg)
    return out


def shorts_config_for_channel_id(channel_id: str) -> ShortsReviewConfig | None:
    cid = (channel_id or "").strip()
    for ch in get_channels():
        if (ch.get("channel_id") or "").strip() == cid:
            return shorts_config_from_channel(ch)
    return None
