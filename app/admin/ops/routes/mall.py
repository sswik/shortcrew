"""숏크루 클릭 로그 수집·조회."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.admin.auth import require_admin
from app.admin.ops.routes import common
from app.admin.ops.routes.instagram_publish import require_ops_token

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


class MallUpsertBody(BaseModel):
    """쿠파스 상품 1개 추가/수정. 키 = channel_id + no (Q=쿠파스 행끼리만 비교).

    None 인 필드는 수정 시 기존 값을 유지한다(추가 시엔 빈칸).
    """

    channel_id: str
    no: int
    name: str | None = None
    image: str | None = None
    deep_link: str | None = None
    product_url: str | None = None
    category: str | None = None
    features: list[str] | str | None = None
    rating: float | None = None
    review_count: int | None = None
    stats_at: str | None = None
    publish_at: str | None = None
    video: str | None = None
    status: str | None = None       # I열. 기본 '게시중'
    price: str | int | None = None  # D열(화면엔 표시 안 함)


def _text(v: str) -> str:
    """USER_ENTERED 에서 날짜·ISO 문자열이 날짜값으로 바뀌지 않게 텍스트로 고정."""
    return "'" + v if v else ""


@router.post("/upsert")
async def upsert_kupas_product(body: MallUpsertBody, _: None = Depends(require_ops_token)):
    """쿠파스 채널 상품탭에 A~Q 한 줄 추가/수정 → 몰 캐시 즉시 무효화. 설계: app/client/mall_kupas.py."""
    from app.admin.ops.channels import get_channels
    from app.admin.ops.services.google_sheets import append_rows, batch_update_cells, get_all_rows
    from app.client.mall_kupas import (
        KUPAS_COLUMNS, KUPAS_SECTION, is_kupas_channel, is_kupas_row, parse_no, parse_publish_at, quoted_range,
    )
    from app.client.mall_products_service import invalidate_mall_products_cache

    cid = body.channel_id.strip()
    if not is_kupas_channel(cid):
        raise HTTPException(status_code=400, detail=f"channel {cid} is not a kupas channel (MALL_KUPAS_CHANNELS)")
    if body.no < 1:
        raise HTTPException(status_code=400, detail="no must be >= 1")
    if body.publish_at and parse_publish_at(body.publish_at) is None:
        raise HTTPException(status_code=400, detail="publish_at must be ISO 8601 (e.g. 2026-10-09T10:30:00Z)")
    channel = next((c for c in get_channels() if c.get("channel_id") == cid), None)
    sheet_id = ((channel or {}).get("google_sheet_id") or "").strip()
    tab = ((channel or {}).get("sheet_tab_name") or "").strip()
    if not sheet_id or not tab:
        raise HTTPException(status_code=404, detail=f"channel {cid} has no product sheet")

    try:
        values = await get_all_rows(sheet_id, tab, "A1:Q2000")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"sheet read failed: {e}")
    header = values[0] if values else []
    rows = values[1:]

    found_at = None  # 시트 행 번호(1-base)
    existing: list = []
    for i, r in enumerate(rows):
        if is_kupas_row(r) and parse_no(str(r[0]) if r else "") == body.no:
            found_at, existing = i + 2, list(r)  # 같은 번호가 여럿이면 마지막 줄(몰 노출과 동일)
    existing += [""] * (17 - len(existing))

    def pick(idx: int, new) -> str:
        if new is None:
            return str(existing[idx] or "") if found_at else ""
        return str(new)

    feats = body.features
    if isinstance(feats, list):
        feats = " · ".join(f.strip() for f in feats if f and f.strip())
    from app.core.config import KST

    today = datetime.now(KST).date().isoformat()
    row = [
        str(body.no),
        pick(1, body.category),
        pick(2, body.name),
        pick(3, body.price),
        pick(4, body.image),
        pick(5, body.product_url),
        pick(6, body.deep_link),
        pick(7, body.video),
        pick(8, body.status) or "게시중",
        _text(pick(9, None)) if found_at else _text(today),
        pick(10, None) if found_at else "",
        pick(11, body.rating),
        pick(12, body.review_count),
        pick(13, feats),
        _text(pick(14, body.stats_at)),
        _text(pick(15, body.publish_at)),
        KUPAS_SECTION,
    ]
    if not row[2]:
        raise HTTPException(status_code=400, detail="name required for a new product")

    try:
        updates = []
        if len(header) < 17 or any(not str(h).strip() for h in header[11:17]):
            updates.append({"range": quoted_range(tab, "L1:Q1"), "values": [list(KUPAS_COLUMNS)]})
        if found_at:
            updates.append({"range": quoted_range(tab, f"A{found_at}:Q{found_at}"), "values": [row]})
            await batch_update_cells(sheet_id, updates)
            action = "updated"
        else:
            if updates:
                await batch_update_cells(sheet_id, updates)
            await append_rows(sheet_id, tab, [row], column_range="A:Q")
            after = await get_all_rows(sheet_id, tab, "A1:Q2000")
            found_at = next(
                (i + 1 for i in range(len(after) - 1, 0, -1)
                 if is_kupas_row(after[i]) and parse_no(str(after[i][0]) if after[i] else "") == body.no),
                None,
            )
            action = "inserted"
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"sheet write failed: {e}")

    invalidate_mall_products_cache(cid)
    return {"ok": True, "action": action, "channel_id": cid, "no": body.no, "sheet_row": found_at}


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
