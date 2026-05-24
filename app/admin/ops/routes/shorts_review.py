"""쇼츠 시트 트리거 리뷰 파이프라인 수동 실행 (어드민)."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.admin.auth import require_admin
from app.admin.deps import get_db
from app.admin.ops.services.shorts_review_config import (
    iter_shorts_review_configs,
    shorts_config_for_channel_id,
)
from app.admin.ops.services.shorts_review_pipeline import run_shorts_review_pipeline_for_channel
from sqlalchemy.orm import Session

router = APIRouter()


class ShortsReviewRunBody(BaseModel):
    channel_id: str | None = Field(
        default=None,
        description="비우면 shorts_automation_enabled 인 채널 전부 순회",
    )
    dry_run: bool = Field(default=False, description="True면 DB INSERT 없이 로그만")
    limit: int | None = Field(
        default=None,
        ge=1,
        description="매칭 행 중 최대 N건만 처리. 비우면 제한 없음",
    )


@router.post("/run")
async def shorts_review_run(
    body: ShortsReviewRunBody,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    gemini = (os.environ.get("GOOGLE_GEMINI_KEY") or "").strip()
    yt = (os.environ.get("YOUTUBE_API_KEY") or "").strip()
    if not gemini:
        return JSONResponse(
            status_code=503,
            content={"error": "GOOGLE_GEMINI_KEY 가 설정되지 않았습니다."},
        )
    if not yt:
        return JSONResponse(
            status_code=503,
            content={"error": "YOUTUBE_API_KEY 가 설정되지 않았습니다."},
        )

    cid = (body.channel_id or "").strip()
    if cid:
        cfg = shorts_config_for_channel_id(cid)
        if cfg is None:
            return JSONResponse(
                status_code=400,
                content={
                    "error": f"채널 {cid!r} 에 쇼츠 자동화 설정이 없거나 비활성입니다.",
                },
            )
        configs = [cfg]
    else:
        configs = iter_shorts_review_configs()
        if not configs:
            return JSONResponse(
                status_code=400,
                content={"error": "실행할 채널이 없습니다. SHORTS_AUTOMATION_ENABLED 및 시트 탭 env 를 확인하세요."},
            )

    lines: list[str] = []
    for cfg in configs:
        part = await run_shorts_review_pipeline_for_channel(
            db,
            cfg,
            gemini_api_key=gemini,
            youtube_api_key=yt,
            dry_run=bool(body.dry_run),
            limit=body.limit,
        )
        lines.extend(part)

    return {"ok": True, "log": lines}
