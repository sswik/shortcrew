"""Jinja 컨텍스트: per-mall 테마 CSS vars + 프로필 메타 파싱."""
from __future__ import annotations

from app.client.mall_theme import (
    get_mall_theme,
    parse_profile_meta_json,
    theme_to_css_vars,
    theme_to_root_style,
    theme_to_style_tag,
)
from models import Influencer


def _client_theme_context(influencer: Influencer | None = None) -> dict[str, object]:
    """Jinja context: mall theme CSS vars + parsed profile meta."""
    theme = get_mall_theme(influencer)
    meta = parse_profile_meta_json(
        getattr(influencer, "profile_meta_json", None) if influencer else None
    )
    return {
        "mall_theme": theme,
        "mall_theme_css": theme_to_css_vars(theme),
        "mall_theme_root_style": theme_to_root_style(theme),
        "mall_theme_style_tag": theme_to_style_tag(theme),
        "profile_meta": meta,
    }
