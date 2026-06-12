"""순수 헬퍼: 클라이언트 IP 추출·User-Agent 파싱·문자열 축약·쿠팡 URL 보강. (앱/DB 비의존)"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import Request


def _client_ip_from_request(request: Request) -> str:
    """프록시 뒤에서도 가능한 한 실제 클라이언트 IP 를 고른다."""
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[0].strip()
    xri = (request.headers.get("x-real-ip") or "").strip()
    if xri:
        return xri
    if request.client:
        return request.client.host or ""
    return ""


def _ua_os_browser(ua: str | None) -> tuple[str, str]:
    """User-Agent 문자열에서 대략적인 OS·브라우저 라벨만 추출한다(외부 라이브러리 없음)."""
    u = (ua or "").strip()
    if not u:
        return ("—", "—")
    ul = u.lower()

    if "windows nt" in ul:
        os_label = "Windows"
    elif "android" in ul:
        os_label = "Android"
    elif "ipad" in ul or "cpu os " in ul or "iphone" in ul:
        os_label = "iPadOS" if "ipad" in ul else "iOS"
    elif "mac os x" in ul or "macintosh" in ul:
        os_label = "macOS"
    elif "linux" in ul:
        os_label = "Linux"
    else:
        os_label = "기타"

    if "edg/" in ul or "edgios" in ul or "edga/" in ul:
        browser_label = "Edge"
    elif "opr/" in ul or "opera" in ul:
        browser_label = "Opera"
    elif "samsungbrowser" in ul:
        browser_label = "Samsung Internet"
    elif "firefox/" in ul or "fxios/" in ul:
        browser_label = "Firefox"
    elif "crios/" in ul:
        browser_label = "Chrome"
    elif "chrome/" in ul and "chromium" not in ul:
        browser_label = "Chrome"
    elif "safari/" in ul and ("chrome/" not in ul and "crios/" not in ul):
        browser_label = "Safari"
    elif "safari/" in ul:
        browser_label = "Safari"
    else:
        browser_label = "기타"

    return (os_label, browser_label)


def _ellipsis_middle(s: str, *, max_chars: int) -> str:
    t = s.strip()
    if len(t) <= max_chars:
        return t
    if max_chars <= 3:
        return t[:max_chars]
    head = (max_chars - 1) // 2
    tail = max_chars - 1 - head
    return f"{t[:head]}…{t[-tail:]}"


def enrich_coupang_url_for_public(url: str, *, lptag: str) -> str:
    """쿠팡 도메인이면 lptag 쿼리를 보강한다(shop-products.js `withCoupangPartnerQuery`와 동일 규칙)."""
    u = (url or "").strip()
    if not u:
        return ""
    try:
        parts = urlparse(u)
    except ValueError:
        return u
    host = (parts.hostname or "").lower()
    if "coupang.com" not in host:
        return u
    q = list(parse_qsl(parts.query, keep_blank_values=True))
    keys_lower = {k.lower() for k, _ in q}
    lp = (lptag or "").strip()
    if lp and "lptag" not in keys_lower:
        q.append(("lptag", lp))
    new_query = urlencode(q, doseq=True)
    return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))
