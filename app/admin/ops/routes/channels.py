"""채널 목록·설정(JSON 오버레이) API."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.admin.auth import require_admin
from app.admin.ops.routes import common

router = APIRouter()


@router.get("/channels")
async def list_channels(_: None = Depends(require_admin)):
    """드롭다운용 채널 목록. 인증 필요."""
    from app.admin.ops.channels import get_channels

    return {"channels": get_channels()}


@router.get("/channels/{channel_id}/settings")
async def get_channel_settings(
    channel_id: str,
    _: None = Depends(require_admin),
):
    """특정 채널의 설정(monitor_keywords 등) 반환. JSON에 없으면 채널 기본값."""
    from app.admin.ops.channels import get_channels

    channel = next((c for c in get_channels() if c.get("channel_id") == channel_id), None)
    if not channel:
        return JSONResponse(status_code=404, content={"error": "channel not found"})
    settings = common.load_channel_settings()
    channel_data = settings.get(channel_id) or {}
    monitor_keywords = channel_data.get("monitor_keywords")
    if monitor_keywords is None:
        monitor_keywords = channel.get("monitor_keywords") or []
    return {"channel_id": channel_id, "monitor_keywords": monitor_keywords}


class ChannelSettingsBody(BaseModel):
    monitor_keywords: list[str]


@router.post("/channels/{channel_id}/settings")
async def save_channel_settings(
    channel_id: str,
    body: ChannelSettingsBody,
    _: None = Depends(require_admin),
):
    """채널 설정(monitor_keywords)을 JSON 파일에 저장."""
    from app.admin.ops.channels import get_channels

    channel = next((c for c in get_channels() if c.get("channel_id") == channel_id), None)
    if not channel:
        return JSONResponse(status_code=404, content={"error": "channel not found"})
    settings = common.load_channel_settings()
    settings[channel_id] = settings.get(channel_id) or {}
    settings[channel_id]["monitor_keywords"] = body.monitor_keywords or []
    common.save_channel_settings(settings)
    return {"ok": True, "channel_id": channel_id, "monitor_keywords": body.monitor_keywords}
