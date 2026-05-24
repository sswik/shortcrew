"""구글 시트 두 탭 필터 + 상품명 조인 (쇼츠 리뷰 파이프라인)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from app.admin.ops.services.shorts_name_normalize import names_equivalent
from app.admin.ops.services.shorts_review_config import ShortsReviewConfig


def _cell(row: list[Any], col_idx: int) -> str:
    if col_idx < 0 or col_idx >= len(row):
        return ""
    v = row[col_idx]
    if v is None:
        return ""
    return str(v).strip()


@dataclass(frozen=True)
class MatchedShortsRow:
    youtube_url: str
    video_id: str
    plan_product_name: str
    deep_link: str


def youtube_video_id_from_url(url: str) -> str | None:
    """YouTube watch / shorts / youtu.be 에서 video id 추출."""
    from urllib.parse import parse_qs, urlparse

    u = (url or "").strip()
    if not u:
        return None
    if "youtu.be/" in u:
        part = u.split("youtu.be/", 1)[1].split("?", 1)[0].split("/", 1)[0].strip()
        return part[:32] if part else None
    try:
        p = urlparse(u)
    except ValueError:
        return None
    host = (p.hostname or "").lower()
    if "youtube.com" not in host and "youtube.co.kr" not in host and "youtu.be" not in host:
        return None
    q = parse_qs(p.query)
    if "v" in q and q["v"] and (q["v"][0] or "").strip():
        return (q["v"][0].strip())[:32]
    path = p.path or ""
    if "/shorts/" in path:
        seg = path.split("/shorts/", 1)[-1].split("/")[0].strip()
        return seg[:32] if seg else None
    if "/live/" in path:
        seg = path.split("/live/", 1)[-1].split("/")[0].strip()
        return seg[:32] if seg else None
    return None


def _looks_like_youtube_url(url: str) -> bool:
    u = (url or "").strip().lower()
    return "youtube.com" in u or "youtu.be/" in u


def parse_sheet_date_cell(raw: Any) -> date | None:
    """시트 D열 등: 문자열·숫자(일련번호)·날짜만 파싱. 인식 실패 시 None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        n = float(raw)
        if not (20000 <= n < 100000):
            return None
        base = datetime(1899, 12, 30)
        return (base + timedelta(days=int(n))).date()
    s = str(raw).strip()
    if not s:
        return None
    if " " in s:
        s = s.split()[0]
    if "T" in s and len(s) > 10:
        s = s.split("T", 1)[0]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%m/%d/%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(s.replace("/", "-"))
    except ValueError:
        return None


def match_shorts_sheet_rows(
    cfg: ShortsReviewConfig,
    plan_rows: list[list[Any]],
    product_rows: list[list[Any]],
    plan_reference_date: date,
) -> list[MatchedShortsRow]:
    """헤더 1행 가정: data는 인덱스 1부터.

    기획 탭: ``plan_status_col`` 이 ``plan_status_value`` 이고,
    ``plan_date_col`` 의 날짜가 ``plan_reference_date`` 와 같을 때만 후보.
    """
    product_deeplink_by_name: list[tuple[str, str]] = []
    for i in range(1, len(product_rows)):
        row = product_rows[i]
        status = _cell(row, cfg.product_status_col)
        if status != cfg.product_status_value:
            continue
        deeplink = _cell(row, cfg.product_deeplink_col)
        if not deeplink:
            continue
        pname = _cell(row, cfg.product_name_col)
        if not pname:
            continue
        product_deeplink_by_name.append((pname, deeplink))

    out: list[MatchedShortsRow] = []
    for i in range(1, len(plan_rows)):
        row = plan_rows[i]
        st = _cell(row, cfg.plan_status_col)
        if st != cfg.plan_status_value:
            continue
        plan_d = parse_sheet_date_cell(_cell(row, cfg.plan_date_col))
        if plan_d != plan_reference_date:
            continue
        yt = _cell(row, cfg.plan_youtube_col)
        if not _looks_like_youtube_url(yt):
            continue
        vid = youtube_video_id_from_url(yt)
        if not vid:
            continue
        pname_plan = _cell(row, cfg.plan_product_col)
        if not pname_plan:
            continue
        deeplink = ""
        for pname_tab, dl in product_deeplink_by_name:
            if names_equivalent(pname_plan, pname_tab):
                deeplink = dl
                break
        if not deeplink:
            continue
        out.append(
            MatchedShortsRow(
                youtube_url=yt,
                video_id=vid,
                plan_product_name=pname_plan,
                deep_link=deeplink,
            )
        )
    return out


def latest_matchable_plan_date(
    cfg: ShortsReviewConfig,
    plan_rows: list[list[Any]],
    product_rows: list[list[Any]],
    *,
    not_after: date,
) -> date | None:
    """오늘 매칭이 0건일 때 fallback용: 조건 충족 행이 존재하는 최신 기획 날짜."""
    product_names: list[str] = []
    for i in range(1, len(product_rows)):
        row = product_rows[i]
        status = _cell(row, cfg.product_status_col)
        if status != cfg.product_status_value:
            continue
        deeplink = _cell(row, cfg.product_deeplink_col)
        if not deeplink:
            continue
        pname = _cell(row, cfg.product_name_col)
        if not pname:
            continue
        product_names.append(pname)

    latest: date | None = None
    for i in range(1, len(plan_rows)):
        row = plan_rows[i]
        st = _cell(row, cfg.plan_status_col)
        if st != cfg.plan_status_value:
            continue
        plan_d = parse_sheet_date_cell(_cell(row, cfg.plan_date_col))
        if plan_d is None or plan_d > not_after:
            continue
        yt = _cell(row, cfg.plan_youtube_col)
        if not _looks_like_youtube_url(yt):
            continue
        vid = youtube_video_id_from_url(yt)
        if not vid:
            continue
        pname_plan = _cell(row, cfg.plan_product_col)
        if not pname_plan:
            continue
        if not any(names_equivalent(pname_plan, pname) for pname in product_names):
            continue
        if latest is None or plan_d > latest:
            latest = plan_d
    return latest
