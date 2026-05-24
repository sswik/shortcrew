"""리뷰 본문 HTML 가공 (클라이언트 페이지용)."""

from __future__ import annotations

import re
from html import unescape

# `append_deeplink_tail` 이 붙이는 블록과 동일 형태를 가정한다.
_SHORTS_CTA_PATTERNS = (
    re.compile(
        r'<p\s+class="shorts-review-cta">\s*'
        r'<a\s+href="([^"]+)"[^>]*>.*?</a>\s*</p>\s*',
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"<p\s+class='shorts-review-cta'>\s*"
        r"<a\s+href='([^']+)'[^>]*>.*?</a>\s*</p>\s*",
        re.IGNORECASE | re.DOTALL,
    ),
)


def split_shorts_review_cta(html: str | None) -> tuple[str, str | None]:
    """본문 끝의 쇼츠 딥링크 CTA 단락을 제거하고 URL만 반환."""
    s = html or ""
    if not s.strip():
        return s, None
    for pat in _SHORTS_CTA_PATTERNS:
        m = pat.search(s)
        if m:
            url = unescape((m.group(1) or "").strip())
            cleaned = pat.sub("", s, count=1)
            return cleaned, url or None
    return s, None
