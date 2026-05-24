"""숏크루 클릭 로그 수집·조회."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.admin.auth import require_admin
from app.admin.ops.routes import common

router = APIRouter()


class MallClickLogBody(BaseModel):
    eventId: str = ""
    channel: str = ""
    mallDomain: str = ""
    pageUrl: str = ""
    pagePath: str = ""
    referrer: str = ""
    clickedAt: str = ""
    sessionId: str = ""
    userAgent: str = ""
    productId: str = ""
    subId: str = ""
    productName: str = ""
    category: str = ""
    deepLink: str = ""
    deepLinkHash: str = ""
    authToken: str = ""


@router.post("/click")
async def collect_mall_click_log(
    request: Request,
    body: MallClickLogBody,
):
    """숏크루(정적 페이지)에서 보내는 클릭 로그 수집."""
    expected_token = common.get_env_secret(request, "MALL_CLICK_LOG_AUTH_TOKEN").strip()
    if expected_token and (body.authToken or "").strip() != expected_token:
        return JSONResponse(status_code=403, content={"ok": False, "error": "invalid token"})

    deep_link = (body.deepLink or "").strip()
    extracted_sub_id = ""
    if deep_link:
        try:
            parsed = urlparse(deep_link)
            extracted_sub_id = (parse_qs(parsed.query).get("subid") or [""])[0].strip()
        except Exception:
            extracted_sub_id = ""

    now = datetime.now(timezone.utc)
    input_channel = (body.channel or "").strip()
    matched_channel = common.find_channel_by_alias(input_channel)
    resolved_channel_id = ""
    resolved_channel_name = ""
    if matched_channel:
        resolved_channel_id = str(matched_channel.get("channel_id") or "").strip()
        resolved_channel_name = str(matched_channel.get("name") or "").strip()

    record = {
        "eventId": (body.eventId or "").strip() or f"evt_{int(now.timestamp() * 1000)}",
        "eventDate": now.date().isoformat(),
        "serverReceivedAt": now.isoformat(),
        "channel": input_channel,
        "channel_id": resolved_channel_id or input_channel,
        "channel_name": resolved_channel_name or input_channel,
        "mallDomain": (body.mallDomain or "").strip(),
        "pageUrl": (body.pageUrl or "").strip(),
        "pagePath": (body.pagePath or "").strip(),
        "referrer": (body.referrer or "").strip(),
        "clickedAt": (body.clickedAt or "").strip(),
        "sessionId": (body.sessionId or "").strip(),
        "userAgent": (body.userAgent or "").strip(),
        "productId": (body.productId or "").strip(),
        "subId": (body.subId or "").strip() or extracted_sub_id,
        "productName": (body.productName or "").strip(),
        "category": (body.category or "").strip(),
        "deepLink": deep_link,
        "deepLinkHash": (body.deepLinkHash or "").strip(),
    }
    await common.append_mall_click_record(record)
    return {"ok": True, "eventId": record["eventId"]}


@router.get("/clicks/recent")
async def get_recent_mall_click_logs(
    channel: str = "",
    days: int = 3,
    limit: int = 100,
    _: None = Depends(require_admin),
):
    """최근 mall 클릭 로그 원본 조회 (디버깅용)."""
    logs = await common.load_recent_mall_click_records(days=days)
    channel = (channel or "").strip()
    if channel:
        logs = common.filter_mall_click_logs_by_channel(logs, channel)
    logs.sort(key=lambda row: str(row.get("serverReceivedAt") or ""), reverse=True)
    safe_limit = max(1, min(int(limit or 100), 500))
    return {"items": logs[:safe_limit], "count": min(len(logs), safe_limit)}


@router.get("/clicks/summary")
async def get_mall_click_summary(
    channel: str = "",
    days: int = 7,
    _: None = Depends(require_admin),
):
    """최근 mall 클릭 로그 요약 (일자/채널/subId 기준)."""
    logs = await common.load_recent_mall_click_records(days=days)
    channel = (channel or "").strip()
    if channel:
        logs = common.filter_mall_click_logs_by_channel(logs, channel)

    daily: dict[str, int] = {}
    sub_ids: dict[str, int] = {}
    unique_sessions: set[str] = set()
    for row in logs:
        date_key = str(row.get("eventDate") or "").strip() or str(row.get("serverReceivedAt") or "")[:10]
        if date_key:
            daily[date_key] = daily.get(date_key, 0) + 1
        sub_id = str(row.get("subId") or "").strip()
        if sub_id:
            sub_ids[sub_id] = sub_ids.get(sub_id, 0) + 1
        session_id = str(row.get("sessionId") or "").strip()
        if session_id:
            unique_sessions.add(session_id)

    return {
        "channel": channel,
        "days": max(1, min(int(days or 7), 31)),
        "total_clicks": len(logs),
        "unique_sessions": len(unique_sessions),
        "daily": [{"date": date_key, "clicks": daily[date_key]} for date_key in sorted(daily.keys())],
        "sub_ids": [
            {"subId": key, "clicks": value}
            for key, value in sorted(sub_ids.items(), key=lambda kv: kv[1], reverse=True)
        ][:20],
    }
