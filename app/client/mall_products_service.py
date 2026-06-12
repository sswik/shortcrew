"""공개 몰 상품 프록시: Apps Script 웹앱 JSON 을 서버가 받아 캐시·날짜셔플 후 반환."""
from __future__ import annotations

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
        raise HTTPException(status_code=503, detail="mall_products_api_url not configured")
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
        if isinstance(items, list) and len(items) > 1:
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
