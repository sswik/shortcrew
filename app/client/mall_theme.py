"""ShortCrew V2.0 mall theme parsing and CSS variable injection."""

from __future__ import annotations

import json
import re
from typing import Any

# PDF §6 — global fallback when Influencer.mall_theme_json is empty
SHORTCREW_DEFAULT_THEME: dict[str, str] = {
    "background": "#121212",
    "card": "#1E1E1E",
    "accent": "#00C2D1",
    "textMain": "#FFFFFF",
    "textSub": "#A3A3A3",
    "border": "#2E2E2E",
    "cta": "#FFB800",
    "ctaHover": "#E6A600",
    "accentDark": "#0098A3",
}

_THEME_KEYS = frozenset(SHORTCREW_DEFAULT_THEME.keys())
_HEX_RE = re.compile(r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")


def _expand_hex(hex_color: str) -> str:
    h = hex_color.strip()
    if not h.startswith("#"):
        h = "#" + h
    if not _HEX_RE.match(h):
        return ""
    if len(h) == 4:
        return "#" + "".join(c * 2 for c in h[1:])
    return h.upper()


def parse_profile_meta_json(raw: str | None) -> dict[str, Any]:
    """Parse Influencer.profile_meta_json (mbti, category, fandom_name, …)."""
    if not raw or not str(raw).strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if v is not None and str(v).strip() != ""}


def parse_mall_theme_json(raw: str | None) -> dict[str, str]:
    """Parse custom theme JSON; invalid/missing keys fall back to SHORTCREW_DEFAULT_THEME."""
    base = dict(SHORTCREW_DEFAULT_THEME)
    if not raw or not str(raw).strip():
        return base
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return base
    if not isinstance(data, dict):
        return base
    for key in _THEME_KEYS:
        val = data.get(key)
        if val is None:
            continue
        normalized = _expand_hex(str(val).strip())
        if normalized:
            base[key] = normalized
    return base


def get_mall_theme(influencer: Any | None) -> dict[str, str]:
    """Resolved theme for an influencer (or global default)."""
    if influencer is None:
        return dict(SHORTCREW_DEFAULT_THEME)
    raw = getattr(influencer, "mall_theme_json", None)
    return parse_mall_theme_json(raw if isinstance(raw, str) else None)


def theme_to_root_style(theme: dict[str, str] | None = None) -> str:
    """Complete `:root { ... }` rule for a <style> tag (avoids empty/partial CSS in templates)."""
    return f":root{{{theme_to_css_vars(theme)}}}"


def theme_to_style_tag(theme: dict[str, str] | None = None) -> str:
    """Full <style> element HTML — keeps Jinja out of <style> bodies (editor CSS lint)."""
    root = theme_to_root_style(theme)
    if not root:
        return ""
    return f'<style id="mall-theme-overrides">{root}</style>'


def theme_to_css_vars(theme: dict[str, str] | None = None) -> str:
    """CSS custom property declarations (without selector)."""
    t = theme or SHORTCREW_DEFAULT_THEME
    bg = t.get("background", SHORTCREW_DEFAULT_THEME["background"])
    card = t.get("card", SHORTCREW_DEFAULT_THEME["card"])
    accent = t.get("accent", SHORTCREW_DEFAULT_THEME["accent"])
    text_main = t.get("textMain", SHORTCREW_DEFAULT_THEME["textMain"])
    text_sub = t.get("textSub", SHORTCREW_DEFAULT_THEME["textSub"])
    border = t.get("border", SHORTCREW_DEFAULT_THEME["border"])
    cta = t.get("cta", SHORTCREW_DEFAULT_THEME["cta"])
    cta_hover = t.get("ctaHover", SHORTCREW_DEFAULT_THEME["ctaHover"])
    accent_dark = t.get("accentDark", SHORTCREW_DEFAULT_THEME["accentDark"])
    return (
        f"--bg-base:{bg};"
        f"--surface-card:{card};"
        f"--surface-muted:#262626;"
        f"--cyan-main:{accent};"
        f"--cyan-dark:{accent_dark};"
        f"--amber-cta:{cta};"
        f"--amber-hover:{cta_hover};"
        f"--text-main:{text_main};"
        f"--text-muted:{text_sub};"
        f"--border-line:{border};"
    )


def tap_highlight_rgba(hex_color: str, alpha: float = 0.35) -> str:
    """탭 하이라이트/버튼용 rgba (accent 기반). pump 몰 shop.html 의 `--tap-accent`."""
    s = _expand_hex((hex_color or "").strip())
    if len(s) != 7:
        s = SHORTCREW_DEFAULT_THEME.get("accent", "#7c3aed")
    try:
        r, g, b = int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16)
    except ValueError:
        r, g, b = 124, 58, 237
    return f"rgba({r}, {g}, {b}, {alpha})"


def pump_mall_theme(pump: Any | None) -> dict[str, str]:
    """pump 몰 템플릿용 테마 dict. `mall_theme_json`(HEX) 병합 + `warning` 보장."""
    theme = get_mall_theme(pump)
    theme.setdefault("warning", "#f97316")
    return theme


def validate_profile_meta_json(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    """Return (parsed dict, error message). Empty string → empty dict."""
    text = (raw or "").strip()
    if not text:
        return {}, None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"JSON 형식 오류: {e}"
    if not isinstance(data, dict):
        return None, "profile_meta_json은 JSON 객체여야 합니다."
    return {str(k): v for k, v in data.items()}, None


def validate_mall_theme_json(raw: str) -> tuple[dict[str, str] | None, str | None]:
    """Return (parsed theme dict, error message)."""
    text = (raw or "").strip()
    if not text:
        return {}, None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"JSON 형식 오류: {e}"
    if not isinstance(data, dict):
        return None, "mall_theme_json은 JSON 객체여야 합니다."
    out: dict[str, str] = {}
    for key, val in data.items():
        if key not in _THEME_KEYS:
            continue
        normalized = _expand_hex(str(val).strip())
        if not normalized:
            return None, f"잘못된 HEX 색상: {key}={val}"
        out[key] = normalized
    return out, None
