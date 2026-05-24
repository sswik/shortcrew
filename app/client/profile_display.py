"""공개 홈 큐카드용 프로필 표시 문자열 (분야·이름)."""

from __future__ import annotations

import re
from typing import Any

# profile_meta.category 또는 name_slug → 홈 카드용 한글 분야명
CATEGORY_SLUG_LABELS: dict[str, str] = {
    "golf": "골프",
    "soccer": "축구",
    "football": "축구",
    "tennis": "테니스",
    "shopping": "쇼핑",
    "beauty": "뷰티",
    "fashion": "패션",
    "food": "푸드",
    "pet": "반려동물",
    "tech": "테크",
    "game": "게임",
    "travel": "여행",
    "parenting": "육아",
    "health": "헬스",
    "fitness": "피트니스",
}


def _normalize_category_token(raw: str) -> str:
    """golf / 골프 / 골프인플루언서 → 표시용 분야명."""
    s = (raw or "").strip()
    if not s:
        return ""
    key = s.lower().replace(" ", "").replace("_", "-")
    if key in CATEGORY_SLUG_LABELS:
        return CATEGORY_SLUG_LABELS[key]
    if s.endswith("인플루언서"):
        s = s[: -len("인플루언서")].strip()
    if s.lower() in CATEGORY_SLUG_LABELS:
        return CATEGORY_SLUG_LABELS[s.lower()]
    return s


def category_from_display_name(display_name: str) -> str:
    """`오세련픽(골프인플루언서)` → `골프`."""
    name = (display_name or "").strip()
    m = re.search(r"\(([^)]+)\)", name)
    if not m:
        return ""
    return _normalize_category_token(m.group(1))


def influencer_short_name(display_name: str) -> str:
    """`오세련픽` / `오세련픽(골프인플루언서)` → `오세련`."""
    name = (display_name or "").strip()
    if "(" in name:
        name = name.split("(", 1)[0].strip()
    if name.endswith("픽"):
        name = name[:-1].strip()
    return name


def resolve_category_label(
    meta: dict[str, Any] | None,
    *,
    display_name: str = "",
    name_slug: str = "",
) -> str:
    meta = meta or {}
    for key in ("category", "field", "분야", "genre"):
        val = meta.get(key)
        if val is not None and str(val).strip():
            label = _normalize_category_token(str(val))
            if label:
                return label
    from_name = category_from_display_name(display_name)
    if from_name:
        return from_name
    slug = (name_slug or "").strip().lower()
    if slug in CATEGORY_SLUG_LABELS:
        return CATEGORY_SLUG_LABELS[slug]
    return ""


def format_cue_card_tagline(
    display_name: str,
    name_slug: str = "",
    meta: dict[str, Any] | None = None,
) -> str:
    """`{분야} 인플루언서 {이름}입니다.` (분야 없으면 이름만)."""
    category = resolve_category_label(meta, display_name=display_name, name_slug=name_slug)
    short_name = influencer_short_name(display_name) or (display_name or "").strip()
    if category and short_name:
        return f"{category} 인플루언서 {short_name}입니다."
    if short_name:
        return f"인플루언서 {short_name}입니다."
    return "숏크루 크루입니다."
