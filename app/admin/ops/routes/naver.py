"""네이버 데이터랩 트렌드 API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.admin.auth import require_admin
from app.admin.ops.routes import common

router = APIRouter()


@router.get("/trend")
async def naver_trend_keywords(
    request: Request,
    channel_id: str = "",
    _: None = Depends(require_admin),
):
    """채널별 네이버 트렌드 투트랙: discovery(실시간 발굴) + monitoring(관심사 모니터링)."""
    if not channel_id.strip():
        return {"discovery": [], "monitoring": [], "seed_keywords": [], "seed_meta": {}, "error": "channel_id required"}
    from app.admin.ops.channels import get_channels

    channel = next((c for c in get_channels() if c.get("channel_id") == channel_id.strip()), None)
    if not channel:
        return {"discovery": [], "monitoring": [], "seed_keywords": [], "seed_meta": {}, "error": "channel not found"}
    client_id = common.get_env_secret(request, "NAVER_CLIENT_ID")
    client_secret = common.get_env_secret(request, "NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        return {"discovery": [], "monitoring": [], "seed_keywords": [], "seed_meta": {}, "error": "Naver API not configured"}
    raw = channel.get("naver_category_id") or "50000000"
    category_ids = [raw] if isinstance(raw, str) else list(raw) if raw else ["50000000"]
    trend_keywords = channel.get("trend_keywords") or []
    settings = common.load_channel_settings()
    channel_settings = settings.get(channel_id.strip()) or {}
    monitor_keywords = channel_settings.get("monitor_keywords")
    if monitor_keywords is None:
        monitor_keywords = channel.get("monitor_keywords") or []
    from app.admin.ops.services.naver_datalab import get_naver_trend_two_track

    try:
        coupang_access_key = common.get_env_secret(request, "COUPANG_ACCESS_KEY")
        coupang_secret_key = common.get_env_secret(request, "COUPANG_SECRET_KEY")
        result = await get_naver_trend_two_track(
            client_id,
            client_secret,
            category_ids,
            trend_keywords,
            monitor_keywords,
            coupang_access_key=coupang_access_key,
            coupang_secret_key=coupang_secret_key,
            target_count=20,
        )
        return {
            "discovery": result.get("discovery", []),
            "monitoring": result.get("monitoring", []),
            "seed_keywords": result.get("seed_keywords", []),
            "seed_meta": result.get("seed_meta", {}),
        }
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"discovery": [], "monitoring": [], "seed_keywords": [], "seed_meta": {}, "error": str(e)},
        )
