"""펌프 몰 블로그 서비스 — Gemini 글 생성 · 유튜브 임베드 · IG 이미지 발행.

정책
----
- 각 글은 **상품 이미지 1개 필수**(product_image_url 비면 생성 거부).
- 글 성격: 정보성 + 상품리뷰 혼합(gemini_review_draft 재사용).
- 글 마지막에 연관 유튜브 영상 임베드(youtube_url 있으면).
- IG 발행: 대표 상품이미지 1장 + 캡션 → 채널 IG 계정(CHANNEL_{id}_IG_*).
- Salog 로직은 참고만 했고 코드는 섞지 않는다(shortcrew 네이티브).
"""
from __future__ import annotations

import os
import re

import httpx

from app.admin.ops.channels import get_channels
from app.admin.ops.routes.dm import _ig_account
from app.admin.ops.services.gemini_review_draft import generate_review_draft

_YT_ID = re.compile(r"(?:shorts/|watch\?v=|youtu\.be/|/v/|embed/)([0-9A-Za-z_-]{11})")


def channel_id_for_pump_slug(pump_slug: str) -> str:
    """`mall_pump_slug` → 채널 `channel_id`(00식). 못 찾으면 빈 문자열."""
    s = (pump_slug or "").strip().lower()
    if not s:
        return ""
    for ch in get_channels():
        if (ch.get("mall_pump_slug") or "").strip().lower() == s:
            return (ch.get("channel_id") or "").strip()
    return ""


def youtube_embed_url(url: str) -> str:
    """youtube 링크(shorts/watch/youtu.be) → `/embed/{id}`. 못 뽑으면 빈 문자열."""
    m = _YT_ID.search(url or "")
    if not m:
        return ""
    return f"https://www.youtube.com/embed/{m.group(1)}"


def youtube_embed_html(url: str) -> str:
    """글 마지막 임베드용 iframe HTML(반응형). 유효 URL 없으면 빈 문자열."""
    embed = youtube_embed_url(url)
    if not embed:
        return ""
    return (
        '<div class="blog-yt-embed" style="position:relative;width:100%;'
        'aspect-ratio:16/9;margin:1.5rem 0;border-radius:14px;overflow:hidden;">'
        f'<iframe src="{embed}" title="관련 영상" loading="lazy" '
        'style="position:absolute;inset:0;width:100%;height:100%;border:0;" '
        'allow="accelerometer;autoplay;clipboard-write;encrypted-media;gyroscope;picture-in-picture" '
        "allowfullscreen></iframe></div>"
    )


async def generate_blog_fields(
    *,
    pump_slug: str,
    pump_display: str,
    product_title: str,
    product_price: float,
    product_url: str,
    product_image_url: str,
    topic: str = "",
    youtube_url: str = "",
) -> dict:
    """Gemini 로 블로그 글 생성 → BlogPost 필드 dict. 상품이미지 없으면 ValueError."""
    if not (product_image_url or "").strip():
        raise ValueError("상품 이미지(product_image_url)가 필요합니다 — 텍스트만인 글은 허용되지 않습니다.")
    gem_key = (os.environ.get("GOOGLE_GEMINI_KEY") or "").strip()
    if not gem_key:
        raise ValueError("GOOGLE_GEMINI_KEY 미설정")
    extra = (
        f"이 글은 '{topic}' 주제의 쇼츠 영상과 연결됩니다. 도입부에 해당 주제 맥락을 자연스럽게 녹이고, "
        "정보성 설명과 상품 리뷰를 자연스럽게 섞으세요."
        if topic
        else "정보성 설명과 상품 리뷰를 자연스럽게 섞으세요."
    )
    draft = await generate_review_draft(
        gem_key,
        influencer_display=pump_display or pump_slug,
        influencer_slug=pump_slug,
        product_title=product_title,
        product_price=product_price,
        product_url=product_url,
        image_url=product_image_url,
        extra_instruction=extra,
    )
    title = (draft.get("title") or product_title)[:255]
    body = draft.get("html") or ""
    excerpt = re.sub(r"<[^>]+>", "", body)[:300].strip()
    return {
        "pump_slug": pump_slug,
        "title": title,
        "body_html": body,
        "excerpt": excerpt,
        "product_image_url": product_image_url.strip(),
        "product_title": (product_title or "")[:255],
        "product_deeplink": (product_url or "")[:1200],
        "thumbnail": product_image_url.strip(),
        "youtube_url": (youtube_url or "").strip(),
        "source_topic": (topic or "")[:255],
        "status": "draft",
    }


def build_ig_caption(*, title: str, excerpt: str, deeplink: str, pump_display: str = "") -> str:
    """IG 캡션(대표 1장 피드용): 제목 + 요약 + 구매링크 + 해시태그."""
    parts = [title.strip()]
    if excerpt.strip():
        parts.append(excerpt.strip()[:280])
    if deeplink.strip():
        parts.append(f"🛒 {deeplink.strip()}")
    tag = re.sub(r"[^0-9A-Za-z가-힣]", "", (pump_display or ""))
    parts.append(f"#{tag} #쇼핑 #추천템" if tag else "#쇼핑 #추천템")
    parts.append("이 게시물은 쿠팡 파트너스 활동의 일환으로 수수료를 제공받습니다.")
    return "\n\n".join(parts)


async def publish_image_to_ig(*, channel_id: str, image_url: str, caption: str, dry_run: bool = False) -> dict:
    """대표 상품이미지 1장 + 캡션 → 채널 IG 피드 발행. media_id 반환.

    이미지 컨테이너는 인코딩 폴링 없이 바로 media_publish 가능.
    """
    cid = (channel_id or "").strip()
    if not cid or not (image_url or "").strip():
        raise ValueError("channel_id, image_url required")
    acct, token = _ig_account(cid)
    if not acct or not token:
        raise ValueError(f"channel {cid} has no IG account/token")
    ver = (os.environ.get("IG_GRAPH_API_VERSION") or "v21.0").strip() or "v21.0"
    base = f"https://graph.instagram.com/{ver}"
    create_payload = {"image_url": image_url.strip(), "caption": caption or ""}
    if dry_run:
        return {"dry_run": True, "channel_id": cid, "ig_account_id": acct,
                "create_url": f"{base}/{acct}/media", "create_payload": create_payload}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(f"{base}/{acct}/media", data={**create_payload, "access_token": token})
        if r.status_code >= 400:
            raise RuntimeError(f"graph create {r.status_code}: {r.text[:300]}")
        creation_id = str(r.json().get("id") or "").strip()
        if not creation_id:
            raise RuntimeError(f"no creation id: {r.text[:200]}")
        r2 = await client.post(f"{base}/{acct}/media_publish",
                               data={"creation_id": creation_id, "access_token": token})
        if r2.status_code >= 400:
            raise RuntimeError(f"graph publish {r2.status_code}: {r2.text[:300]}")
        media_id = str(r2.json().get("id") or "").strip()
        if not media_id:
            raise RuntimeError(f"publish failed: {r2.text[:200]}")
    return {"ok": True, "channel_id": cid, "creation_id": creation_id, "media_id": media_id}
