"""공개 몰 상품 프록시: Apps Script 웹앱 JSON 을 서버가 받아 캐시·날짜셔플 후 반환.

Apps Script URL 이 없는 채널(예: 안지아)은 서버가 채널 구글 시트(탭)를 **직접 읽어**
같은 형태의 상품 JSON 으로 반환한다(소스는 동일하게 '시트', Apps Script 불필요).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from datetime import date
from threading import Lock
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from fastapi.responses import Response

logger = logging.getLogger(__name__)

# 쿠팡 썸네일 프록시(Cloudflare Workers) 기본값. 전역 env COUPANG_IMAGE_WORKER_BASE 비면 사용.
DEFAULT_COUPANG_IMAGE_WORKER = "https://image.shortcrew.co.kr/"

_MALL_PRODUCTS_CACHE_TTL_SECONDS = float(
    (os.environ.get("MALL_PRODUCTS_CACHE_TTL_SECONDS") or "45").strip() or "45"
)
_mall_products_cache_lock = Lock()
_mall_products_cache: dict[str, tuple[float, bytes, str]] = {}


def _sheet_direct_products_response(cid: str, channel: dict, now: float) -> Response:
    """Apps Script 없이 채널 구글 시트(탭)를 서버가 직접 읽어 상품 JSON 으로 반환.

    시트 컬럼(build_rows 스펙): B(카테고리) C(상품명) D(가격) E(이미지URL)
    F(쿠팡URL) G(딥링크) I(게시상태). 게시상태 '게시중'만 노출.
    """
    sheet_id = (channel.get("google_sheet_id") or "").strip()
    tab = (channel.get("sheet_tab_name") or "상품목록").strip()
    items: list[dict] = []
    if sheet_id:
        from app.admin.ops.services.google_sheets import get_all_rows
        try:
            rows = asyncio.run(get_all_rows(sheet_id, tab, "A2:K1000"))
        except Exception as e:
            logger.warning("mall_sheet_direct_read_error cid=%s tab=%s err=%s", cid, tab, e)
            rows = []
        for r in rows:
            if len(r) < 9:
                continue
            status = (r[8] or "").strip()
            name = (r[2] or "").strip()
            if status != "게시중" or not name:
                continue
            items.append({
                "category": (r[1] or "").strip(),
                "productName": name,
                "price": r[3],
                "imageUrl": (r[4] or "").strip(),
                "productUrl": (r[5] or "").strip(),
                "deepLink": (r[6] or "").strip(),
            })
    # 기본은 큐레이션 고정순서(시트 행 순서=번호). env MALL_SHUFFLE_DAILY=1 이면 일일셔플.
    if len(items) > 1 and (os.environ.get("MALL_SHUFFLE_DAILY") or "").strip().lower() in ("1", "true", "yes", "on"):
        random.Random(str(date.today())).shuffle(items)
    body = json.dumps(items, ensure_ascii=False).encode()
    with _mall_products_cache_lock:
        _mall_products_cache[cid] = (
            now + max(1.0, _MALL_PRODUCTS_CACHE_TTL_SECONDS),
            body,
            "application/json",
        )
    return Response(content=body, media_type="application/json")


def mall_products_response(channel_id: str = "") -> Response:
    """Apps Script 상품 JSON 을 서버가 대신 받아 돌려준다(브라우저 CORS 회피).

    `channel_id` 는 roster 의 `channel_id`(예: 201)로 채널을 고르고, 웹앱에 붙는 `?channel=` 값은
    `MALL_PRODUCTS_CHANNEL_PARAM`(비우면 `201`과 동일) — 샘플 short-mall-template 의 `APPS_SCRIPT_CHANNEL` 과 맞출 것.
    """
    from app.admin.ops.channels import get_channels

    cid = (channel_id or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="channel_id required")

    now = time.monotonic()
    with _mall_products_cache_lock:
        cached = _mall_products_cache.get(cid)
    if cached is not None:
        expires_at, cached_content, cached_media_type = cached
        if expires_at > now:
            return Response(content=cached_content, media_type=cached_media_type)
        with _mall_products_cache_lock:
            current = _mall_products_cache.get(cid)
            if current is not None and current[0] <= now:
                _mall_products_cache.pop(cid, None)

    channel = next((c for c in get_channels() if c.get("channel_id") == cid), None)
    if channel is None:
        raise HTTPException(status_code=404, detail="channel not found")
    base = (channel.get("mall_products_api_url") or "").strip()
    if not base:
        # Apps Script 미설정 채널(안지아 등) → 채널 구글 시트(탭)를 서버가 직접 읽어 노출
        return _sheet_direct_products_response(cid, channel, now)
    chan_q = (channel.get("mall_products_channel_param") or "").strip() or cid
    sep = "?" if "?" not in base else "&"
    target = f"{base}{sep}channel={quote(chan_q, safe='')}"
    headers = {
        "Accept": "application/json, text/plain;q=0.9,*/*;q=0.8",
        "User-Agent": "Shortcrew/1.0 mall-products-proxy",
    }
    try:
        with httpx.Client(timeout=45.0, follow_redirects=True) as client:
            resp = client.get(target, headers=headers)
    except httpx.RequestError as e:
        logger.warning("mall_products_proxy request_error url=%s err=%s", target[:160], e)
        raise HTTPException(status_code=502, detail=f"upstream request failed: {e!s}") from e

    ct_lower = (resp.headers.get("content-type") or "").lower()
    body_preview = (resp.text or "")[:500].replace("\n", " ")

    if resp.status_code >= 400:
        logger.warning(
            "mall_products_proxy bad_status=%s ct=%s body=%s",
            resp.status_code,
            ct_lower,
            body_preview,
        )
        raise HTTPException(
            status_code=502,
            detail=f"upstream HTTP {resp.status_code}: {body_preview}",
        )
    if "text/html" in ct_lower and (resp.text or "").lstrip().lower().startswith("<!doctype"):
        logger.warning("mall_products_proxy got html url=%s", target[:160])
        raise HTTPException(
            status_code=502,
            detail=(
                "웹앱이 HTML을 돌려줬습니다(JSON 아님). 배포 '실행 URL'·액세스 '누구나'·"
                "CHANNEL_*_MALL_PRODUCTS_CHANNEL_PARAM(샘플 config 의 ?channel= 값) 확인."
            ),
        )

    ct = (resp.headers.get("content-type") or "application/json").split(";", 1)[0].strip()
    media_type = ct or "application/json"

    body = resp.content
    try:
        items = json.loads(body)
        if (isinstance(items, list) and len(items) > 1
                and (os.environ.get("MALL_SHUFFLE_DAILY") or "").strip().lower() in ("1", "true", "yes", "on")):
            random.Random(str(date.today())).shuffle(items)
            body = json.dumps(items, ensure_ascii=False).encode()
    except (json.JSONDecodeError, TypeError):
        pass

    with _mall_products_cache_lock:
        _mall_products_cache[cid] = (
            time.monotonic() + max(1.0, _MALL_PRODUCTS_CACHE_TTL_SECONDS),
            body,
            media_type,
        )
    return Response(content=body, media_type=media_type)
