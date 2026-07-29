"""인스타 릴스 발행 엔드포인트 — n8n이 드라이브 영상 1개를 채널 IG에 올릴 때 1방 호출.

흐름(전부 서버에서 처리해 n8n은 HTTP 1번이면 끝):
  1) `POST /{ig}/media` (media_type=REELS, video_url=공개직링크) → 컨테이너 생성
  2) `GET /{container}?fields=status_code` 폴링(인코딩 끝날 때까지)
  3) `POST /{ig}/media_publish` (creation_id=) → 실제 발행

인증은 어드민 쿠키(require_admin)가 아니라 `OPS_API_TOKEN`(헤더 `X-Ops-Token`).
토큰·계정 ID는 dm.py 와 동일하게 `CHANNEL_{ID}_IG_*` env 에서 직접 읽는다.
설계: 06.운영가이드/11_인스타자동발행.md.
"""
from __future__ import annotations

import asyncio
import os
import re

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.admin.ops.routes.dm import _ig_account

router = APIRouter()

# Reels 인코딩 폴링 기본값(엔드포인트가 끝까지 기다렸다 발행까지 반환).
_POLL_INTERVAL_S = 3.0
_POLL_MAX_TRIES = 60  # 약 3분


def _graph_version() -> str:
    return (os.environ.get("IG_GRAPH_API_VERSION") or "v21.0").strip() or "v21.0"


def _thumb_offset_ms() -> str | None:
    """릴스 커버 프레임 시점(ms). 인트로 음영 회피용 기본 2000ms.

    `IG_REEL_THUMB_OFFSET_MS` 로 조절(0/비숫자면 미지정 → IG 기본 첫 프레임).
    """
    raw = (os.environ.get("IG_REEL_THUMB_OFFSET_MS") or "2000").strip()
    return raw if raw.isdigit() and int(raw) > 0 else None


def require_ops_token(x_ops_token: str | None = Header(default=None)) -> None:
    """n8n→FastAPI 공유 토큰 검증. OPS_API_TOKEN 미설정이면 503(잠금)."""
    expected = (os.environ.get("OPS_API_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="OPS_API_TOKEN 미설정 — 이 엔드포인트는 잠겨 있습니다.")
    if (x_ops_token or "").strip() != expected:
        raise HTTPException(status_code=401, detail="invalid X-Ops-Token")


class PublishReelBody(BaseModel):
    channel_id: str
    video_url: str
    caption: str = ""
    share_to_feed: bool = True
    dry_run: bool = False


async def _graph_post(client: httpx.AsyncClient, url: str, token: str, data: dict) -> dict:
    r = await client.post(url, data={**data, "access_token": token})
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"graph {r.status_code}: {r.text[:300]}")
    return r.json()


async def _graph_get(client: httpx.AsyncClient, url: str, token: str, params: dict) -> dict:
    r = await client.get(url, params={**params, "access_token": token})
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"graph {r.status_code}: {r.text[:300]}")
    return r.json()


@router.post("/publish-reel")
async def publish_reel(
    body: PublishReelBody,
    _: None = Depends(require_ops_token),
):
    """드라이브 공개 영상 URL → 채널 IG 릴스로 발행. media_id 반환."""
    cid = (body.channel_id or "").strip()
    video_url = (body.video_url or "").strip()
    if not cid or not video_url:
        raise HTTPException(status_code=400, detail="channel_id, video_url required")

    acct, token = _ig_account(cid)
    if not acct or not token:
        raise HTTPException(status_code=400, detail=f"channel {cid} has no IG account/token")

    ver = _graph_version()
    base = f"https://graph.instagram.com/{ver}"
    create_payload = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": body.caption or "",
        "share_to_feed": "true" if body.share_to_feed else "false",
    }
    _thumb = _thumb_offset_ms()
    if _thumb:
        create_payload["thumb_offset"] = _thumb

    if body.dry_run:
        return {
            "dry_run": True,
            "channel_id": cid,
            "ig_account_id": acct,
            "create_url": f"{base}/{acct}/media",
            "create_payload": create_payload,
            "publish_url": f"{base}/{acct}/media_publish",
        }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1) 컨테이너 생성
        created = await _graph_post(client, f"{base}/{acct}/media", token, create_payload)
        creation_id = str(created.get("id") or "").strip()
        if not creation_id:
            raise HTTPException(status_code=502, detail=f"no creation id: {created}")

        # 2) 인코딩 완료 폴링
        status = ""
        for _try in range(_POLL_MAX_TRIES):
            info = await _graph_get(client, f"{base}/{creation_id}", token, {"fields": "status_code"})
            status = str(info.get("status_code") or "").upper()
            if status == "FINISHED":
                break
            if status in ("ERROR", "EXPIRED"):
                raise HTTPException(status_code=502, detail=f"container {status}: {info}")
            await asyncio.sleep(_POLL_INTERVAL_S)
        if status != "FINISHED":
            raise HTTPException(status_code=504, detail=f"container not ready (last={status})")

        # 3) 발행
        published = await _graph_post(
            client, f"{base}/{acct}/media_publish", token, {"creation_id": creation_id}
        )
        media_id = str(published.get("id") or "").strip()
        if not media_id:
            raise HTTPException(status_code=502, detail=f"publish failed: {published}")

        # 4) 퍼머링크(선택, 실패해도 발행은 성공이므로 무시)
        permalink = ""
        try:
            meta = await _graph_get(client, f"{base}/{media_id}", token, {"fields": "permalink"})
            permalink = str(meta.get("permalink") or "")
        except HTTPException:
            permalink = ""

    return {
        "ok": True,
        "channel_id": cid,
        "creation_id": creation_id,
        "media_id": media_id,
        "permalink": permalink,
    }


class ReelFunnelBody(BaseModel):
    """발행된 릴스에 CTA 첫댓글 + 댓글→DM 규칙 자동생성(인플루언서 퍼널)."""

    channel_id: str = ""
    media_id: str = ""          # publish-reel 응답의 media_id
    keyword: str = ""           # 상품 키워드(예: "드라이버") — 이 댓글 달면 DM
    coupang_url: str = ""       # 상품 쿠팡 URL(딥링크 자동생성). deep_link 있으면 무시
    deep_link: str = ""         # 이미 만든 딥링크(우선)
    mall_slug: str = ""         # 몰 링크(shortcrew.co.kr/{slug})
    product_title: str = ""     # 상품명(DM 문구)
    greeting: str = ""          # 인사멘트(비우면 기본)
    cta_comment: str = ""       # CTA 첫댓글(비우면 keyword로 생성)


@router.post("/reel-funnel")
async def setup_reel_funnel(body: ReelFunnelBody, _: None = Depends(require_ops_token)):
    """발행된 릴스에 ① CTA 첫댓글 ② 댓글→DM 규칙(키워드=상품, DM=인사+딥링크+몰링크) 자동생성."""
    import json as _json

    cid = (body.channel_id or "").strip()
    media_id = (body.media_id or "").strip()
    keyword = (body.keyword or "").strip()
    title = (body.product_title or "").strip()
    if not cid or not media_id:
        raise HTTPException(status_code=400, detail="channel_id, media_id required")
    # 키워드 미지정 시 상품명에서 Gemini로 자동 추출(브랜드 제외 상품유형어)
    if not keyword and title:
        gem = (os.environ.get("GOOGLE_GEMINI_KEY") or "").strip()
        if gem:
            from app.admin.ops.services.gemini_curator import derive_dm_keyword

            keyword = (await derive_dm_keyword(title, gem)).strip()
    if not keyword:  # 폴백: 상품명 끝 단어들
        toks = [t for t in re.sub(r"(사용\s*후기|사용후|후기|리뷰|review)", "", title).split() if t]
        keyword = "".join(toks[-2:]) if len(toks) >= 2 else (toks[-1] if toks else "")
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword required (or product_title for auto)")
    acct, token = _ig_account(cid)
    if not acct or not token:
        raise HTTPException(status_code=400, detail=f"channel {cid} has no IG account/token")
    ver = _graph_version()
    base = f"https://graph.instagram.com/{ver}"

    # 1) 딥링크(쿠팡 URL → 딥링크, subId=shortcrew 고정)
    deep = (body.deep_link or "").strip()
    coupang_url = (body.coupang_url or "").strip()
    if not deep and coupang_url:
        from app.admin.ops.services.coupang import generate_deeplinks

        ak = (os.environ.get("COUPANG_ACCESS_KEY") or "").strip()
        sk = (os.environ.get("COUPANG_SECRET_KEY") or "").strip()
        if ak and sk:
            try:
                m = await generate_deeplinks([coupang_url], ak, sk)
                deep = (m.get(coupang_url) or "").strip() or deep
            except Exception:
                deep = deep

    # 2) DM 문구(인사 + 상품 + 몰링크). 딥링크는 dm_link(웹훅이 본문 뒤에 붙임)
    mall_link = f"https://shortcrew.co.kr/{body.mall_slug.strip()}" if (body.mall_slug or "").strip() else ""
    greeting = (body.greeting or "").strip() or "안녕하세요! 😊 관심 가져주셔서 감사해요."
    dm_lines = [greeting, f"문의주신 '{keyword}' 정보 보내드려요 🛒", ""]
    if deep:
        dm_lines += ["[관련 상품]", deep, ""]
    if mall_link:
        dm_lines += ["[더 많은 상품이 궁금하다면?]", mall_link]
    dm_message = "\n".join(dm_lines).strip()

    # 3) CTA 첫댓글(핀 고정은 API 미지원 → 첫댓글로만)
    cta = (body.cta_comment or "").strip() or f"댓글에 '{keyword}' 남겨주시면 상품정보를 DM으로 보내드려요! 🎁"
    comment_id = ""
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            r = await client.post(f"{base}/{media_id}/comments", data={"message": cta, "access_token": token})
            if r.status_code < 400:
                comment_id = str(r.json().get("id") or "")
        except httpx.HTTPError:
            comment_id = ""

    # 4) 댓글→DM 규칙 생성(specific media + keyword)
    from models import DmAutomation, SessionLocal

    with SessionLocal() as db:
        rule = DmAutomation(
            channel_id=cid,
            name=f"[자동] {keyword}",
            target_mode="specific",
            ig_media_id=media_id,
            trigger_type="keyword",
            keywords_json=_json.dumps([keyword], ensure_ascii=False),
            public_reply_enabled=True,
            public_reply_variants_json=_json.dumps(
                ["DM 보내드렸어요! 확인 부탁드려요 📩", "메시지 확인해주세요! 🙌", "DM 도착했어요 ✨"],
                ensure_ascii=False,
            ),
            dm_message=dm_message,
            dm_link="",  # 딥링크는 dm_message([관련 상품])에 이미 포함 → 웹훅 중복부착 방지
            dm_product_ref=(deep or coupang_url) or None,
            dm_product_title=title or None,
            active=True,
        )
        db.add(rule)
        db.commit()
        rule_id = rule.id

    return {
        "ok": True, "channel_id": cid, "media_id": media_id, "rule_id": rule_id,
        "comment_id": comment_id, "keyword": keyword, "deep_link": deep, "mall_link": mall_link,
    }
