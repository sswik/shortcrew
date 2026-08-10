"""인스타 일일 운영 리포트 제어 — 상태 조회·수동 실행(내부 스케줄러와 동일 로직).

인증: `OPS_API_TOKEN`(헤더 `X-Ops-Token`). 스케줄은 앱 내부(ig_report_scheduler)가 담당,
여기선 대상 채널 확인·즉시 실행(미리보기 포함)만 한다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.admin.ops.routes.instagram_publish import require_ops_token
from app.admin.ops.services.ig_report_scheduler import _at, report_channels, run_report_once

router = APIRouter()


@router.get("/status")
def ig_report_status(_: None = Depends(require_ops_token)) -> dict:
    chs = report_channels()
    hh, mm = _at()
    return {"channels": chs, "count": len(chs), "at_kst": f"{hh:02d}:{mm:02d}"}


class RunNowBody(BaseModel):
    dry_run: bool = True  # 기본은 미리보기(디스코드 전송 안 함)


@router.post("/run-now")
async def ig_report_run_now(body: RunNowBody, _: None = Depends(require_ops_token)) -> dict:
    """리포트 즉시 생성. dry_run=false 여야 디스코드로 실제 전송된다."""
    return await run_report_once(dry_run=body.dry_run)
