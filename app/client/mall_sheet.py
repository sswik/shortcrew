"""공개 몰: 인플루언서와 채널·시트 웹앱 URL 매칭."""

from __future__ import annotations

from app.admin.ops.channels import get_channels


def _mall_influencer_aliases(channel: dict) -> set[str]:
    """`MALL_INFLUENCER_SLUG` 에 쉼표·세미콜론으로 여러 슬러그를 넣은 경우(예: soccer-jimin,jimin)."""
    raw = (channel.get("mall_influencer_slug") or "").strip()
    if not raw:
        return set()
    parts: list[str] = []
    for chunk in raw.replace(";", ",").split(","):
        t = chunk.strip()
        if t:
            parts.append(t.lower())
    return set(parts)


def _channel_has_mall_fetch_url(ch: dict) -> bool:
    u = (ch.get("mall_products_api_url") or ch.get("product_delivery_url") or "").strip()
    return bool(u)


def get_mall_channel_for_influencer(
    influencer_name_slug: str,
    influencer_shop_path_slug: str | None = None,
) -> dict | None:
    """`mall_influencer_slug`(또는 쉼표 구분 별칭)이 `name_slug`·`shop_path_slug` 와 맞으면 해당 채널 dict."""
    name_s = (influencer_name_slug or "").strip()
    path_s = (influencer_shop_path_slug or "").strip()
    if not name_s and not path_s:
        return None
    name_l = name_s.lower()
    path_l = path_s.lower() if path_s else ""

    channels = get_channels()
    for ch in channels:
        aliases = _mall_influencer_aliases(ch)
        if not aliases:
            continue
        if name_l in aliases or (path_l and path_l in aliases):
            return ch

    # 로스터에 채널이 1개뿐이면 mall URL만 있으면 슬러그 미일치 시에도 연결(단일 몰·로컬 개발 완화)
    if len(channels) == 1 and _channel_has_mall_fetch_url(channels[0]):
        return channels[0]

    return None


def resolve_mall_products_api(
    influencer_name_slug: str,
    influencer_shop_path_slug: str | None = None,
) -> tuple[str, str]:
    """`(mall_products_api_url, channel_id)` — URL이 비면 몰에서 상품 목록을 불러오지 않는다."""
    ch = get_mall_channel_for_influencer(influencer_name_slug, influencer_shop_path_slug)
    if not ch:
        return "", ""
    url = (ch.get("mall_products_api_url") or "").strip()
    cid = (ch.get("channel_id") or "").strip()
    return url, cid


def mall_heading_for_shop(influencer_display_name: str, channel: dict | None) -> str:
    """채널 `name` 의 괄호 앞(예: OOO픽) 우선, 없으면 `표시이름` + 픽."""
    if channel:
        raw = (channel.get("name") or "").strip()
        short = raw.split("(", 1)[0].strip()
        if short:
            return short
    dn = (influencer_display_name or "").strip()
    if dn.endswith("픽"):
        return dn
    if dn:
        return f"{dn}픽"
    return "픽"
