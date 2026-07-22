"""유튜브→인스타 크로스포스트 전용 엔드포인트.

이 플로우 n8n 은 다른 클라우드라 기존 `/instagram/publish-reel` 과 **분리**한다.
당일 신규 크로스포스트·과거영상 백필 둘 다 이 엔드포인트를 호출한다.
인증: `OPS_API_TOKEN`(헤더 `X-Ops-Token`).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.admin.ops.routes.instagram_publish import require_ops_token
from app.admin.ops.services.youtube_ig_bridge import publish_reel_to_ig

router = APIRouter()


class CrosspostReelBody(BaseModel):
    channel_id: str            # 00식 채널 id (02~37)
    video_url: str             # 공개 직링크(Drive 공개 URL 등) — n8n 이 준비
    caption: str = ""
    share_to_feed: bool = True
    dry_run: bool = False


@router.post("/reel")
async def crosspost_reel(body: CrosspostReelBody, _: None = Depends(require_ops_token)) -> dict:
    """공개 영상 URL → 채널 IG 릴스 발행(컨테이너→폴링→발행). media_id 반환."""
    try:
        return await publish_reel_to_ig(
            channel_id=body.channel_id,
            video_url=body.video_url,
            caption=body.caption,
            share_to_feed=body.share_to_feed,
            dry_run=body.dry_run,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
