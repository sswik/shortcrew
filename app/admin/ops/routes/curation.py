"""큐레이션 스케줄러 제어 — 상태 조회·수동 실행(내부 스케줄러와 동일 로직).

인증: `OPS_API_TOKEN`(헤더 `X-Ops-Token`). 스케줄은 앱 내부(curation_scheduler)가 담당,
여기선 오늘 채널 확인·즉시 실행만. 수동 실행도 Gemini 를 태우니 남발 금지.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.admin.ops.routes.instagram_publish import require_ops_token
from app.admin.ops.services.curation_scheduler import (
    curation_channels,
    run_curation_once,
    todays_channel,
)

router = APIRouter()


@router.get("/status")
def curation_status(_: None = Depends(require_ops_token)) -> dict:
    chs = curation_channels()
    return {"channels": chs, "count": len(chs), "today": todays_channel(chs)}


class RunNowBody(BaseModel):
    channel_id: str = ""       # 비우면 오늘의 채널(로테이션)
    auto_blog: bool | None = None  # None 이면 env(CURATION_AUTO_BLOG) 따름
    max_items: int | None = None   # 이번 실행 상품 개수. None 이면 env(증분). 초기시딩=20 등


@router.post("/run-now")
async def curation_run_now(body: RunNowBody, _: None = Depends(require_ops_token)) -> dict:
    """오늘(또는 지정) 채널 큐레이션 즉시 실행. 스케줄과 동일 로직."""
    return await run_curation_once(
        body.channel_id or None, auto_blog=body.auto_blog, max_items=body.max_items
    )
