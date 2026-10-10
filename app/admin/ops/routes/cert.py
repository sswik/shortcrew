"""Cloud Run 관리형 인증서 만료 감시 — 상태 조회·스케줄 실행.

인증: `OPS_API_TOKEN`(헤더 `X-Ops-Token`). 매일 Cloud Scheduler 가 `/run-now` 를 호출한다.
배경은 `app/admin/ops/services/cert_monitor.py` 주석 참고.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.admin.ops.routes.instagram_publish import require_ops_token
from app.admin.ops.services.cert_monitor import check_cert

router = APIRouter()


@router.get("/status")
async def cert_status(_: None = Depends(require_ops_token)) -> dict:
    """조회만 한다(알림 없음)."""
    return await check_cert(notify=False)


class RunNowBody(BaseModel):
    notify: bool = True


@router.post("/run-now")
async def cert_run_now(body: RunNowBody, _: None = Depends(require_ops_token)) -> dict:
    """만료 임박이면 디스코드 경고까지 보낸다."""
    return await check_cert(notify=body.notify)
