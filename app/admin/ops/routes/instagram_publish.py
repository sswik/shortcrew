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
