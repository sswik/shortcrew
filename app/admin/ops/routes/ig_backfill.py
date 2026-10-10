"""과거영상 → 인스타 백필 제어 — 상태 조회·수동/스케줄 실행.

인증: `OPS_API_TOKEN`(헤더 `X-Ops-Token`).

Cloud Run 에서는 인스턴스가 상시 떠 있지 않아 인프로세스 루프(`IG_BACKFILL_LOOP`)가
동작하지 않는다. 대신 Cloud Scheduler 가 슬롯 시각마다 `/run-now` 를 호출한다.
중복 실행은 `ops_state` 의 분산 잠금이 막는다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.admin.ops.routes.instagram_publish import require_ops_token
from app.admin.ops.services.ig_backfill_scheduler import (
    _channels,
    _slots,
    effective_cap,
    loop_enabled,
    run_backfill_once,
)

router = APIRouter()


@router.get("/status")
def ig_backfill_status(_: None = Depends(require_ops_token)) -> dict:
    chs = _channels()
    return {
        "channels": chs,
        "count": len(chs),
        "cap_per_account": effective_cap(),
        "slots_kst": [f"{h:02d}:{m:02d}" for h, m in _slots()],
        "in_process_loop": loop_enabled(),
    }


class RunNowBody(BaseModel):
    dry_run: bool = True  # 기본은 미리보기(실제 발행 안 함)


@router.post("/run-now")
async def ig_backfill_run_now(body: RunNowBody, _: None = Depends(require_ops_token)) -> dict:
    """백필 1패스 즉시 실행. dry_run=false 여야 실제로 IG 에 발행된다."""
    return await run_backfill_once(dry_run=body.dry_run)
