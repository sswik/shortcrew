"""IG 장기 토큰 자동갱신 제어 — 상태 조회·수동/스케줄 실행.

인증: `OPS_API_TOKEN`(헤더 `X-Ops-Token`).

Cloud Run 에서는 인스턴스가 상시 떠 있지 않아 인프로세스 루프(`IG_TOKEN_REFRESH_LOOP`)가
동작하지 않는다. 대신 Cloud Scheduler 가 매일 `/run-now` 를 호출한다.
실제 갱신은 `IG_TOKEN_REFRESH_EVERY_DAYS`(기본 40일)가 지난 채널만 대상이므로
매일 호출해도 불필요한 재발급은 없다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.admin.ops.routes.instagram_publish import require_ops_token
from app.admin.ops.services.ig_token_refresh import (
    _every_days,
    load_store,
    loop_enabled,
    refresh_all_due,
)

router = APIRouter()

_TTL_S = 60 * 24 * 3600  # IG 장기토큰 60일


@router.get("/status")
def ig_token_status(_: None = Depends(require_ops_token)) -> dict:
    """채널별 마지막 갱신·남은 만료일. 만료 임박분을 눈으로 잡기 위한 용도."""
    store = load_store()
    now = datetime.now(timezone.utc)
    rows = []
    for cid, rec in sorted(store.items(), key=lambda x: (len(x[0]), x[0])):
        ts = str((rec or {}).get("refreshed_at") or "").strip()
        left = None
        if ts:
            try:
                base = datetime.fromisoformat(ts)
                if base.tzinfo is None:
                    base = base.replace(tzinfo=timezone.utc)
                ttl = int((rec or {}).get("expires_in") or _TTL_S)
                left = int(((base + timedelta(seconds=ttl)) - now).total_seconds() // 86400)
            except ValueError:
                left = None
        rows.append({"channel_id": cid, "refreshed_at": ts or None, "days_left": left})
    return {
        "count": len(rows),
        "every_days": _every_days(),
        "in_process_loop": loop_enabled(),
        "channels": rows,
    }


class RunNowBody(BaseModel):
    force: bool = False  # true 면 주기와 무관하게 전 채널 갱신 시도


@router.post("/run-now")
async def ig_token_run_now(body: RunNowBody, _: None = Depends(require_ops_token)) -> dict:
    """갱신 주기가 지난 채널 토큰을 갱신. force=true 면 전 채널 강제."""
    return await refresh_all_due(force=body.force)
