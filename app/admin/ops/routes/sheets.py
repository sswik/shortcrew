"""구글 시트 연동: 상품 전송·목록·상태 수정."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.admin.auth import require_admin
from app.admin.deps import get_db

from ..channels.env_names import channel_env
from . import common

router = APIRouter()
logger = logging.getLogger(__name__)


def _missing_google_sheet_response(channel_id: str) -> JSONResponse:
    cid = (channel_id or "").strip()
    key = channel_env(cid, "FILE_ID") if cid else "CHANNEL_{채널번호}_FILE_ID"
    msg = (
        f"이 채널(channel_id={cid!r})에 구글 스프레드시트 ID가 설정되어 있지 않습니다. "
        f".env에 {key} 를 넣은 뒤 서버를 재시작하세요."
    )
    return JSONResponse(status_code=400, content={"error": msg})


class SheetSendBody(BaseModel):
    channel_id: str
    products: list[dict]


async def _enrich_products_with_deeplinks(
    *,
    request: Request,
    channel: dict,
    channel_id: str,
    products: list[dict],
    db: Session | None,
) -> tuple[list[dict], str, bool]:
    """상품 dict 목록에 `deepLink`를 채운다. 클라이언트가 이미 딥링크를 주면 쿠팡 API를 생략한다.

    Returns:
        (failed_items, mall_shop_url, coupang_api_called)
    """
    from ..services.coupang import generate_deeplinks
    from ..services.mall_tracking import mall_shop_url_for_channel

    mall_shop_url = mall_shop_url_for_channel(channel, db=db, request=request)

    access_key = common.get_env_secret(request, "COUPANG_ACCESS_KEY")
    secret_key = common.get_env_secret(request, "COUPANG_SECRET_KEY")

    urls_to_convert: list[str] = []
    products_needing_api: list[dict] = []

    for p in products:
        if not isinstance(p, dict):
            continue
        pid = p.get("productId")
        if pid:
            from app.admin.ops.services.coupang import clean_product_url

            # itemId/vendorItemId 보존(인스타 콜드세션 상세직행) — subId 유실 없음(검증완료)
            clean_url = clean_product_url(pid, p.get("productUrl") or "")
            p["_clean_url"] = clean_url
            dl = str(p.get("deepLink") or "").strip()
            if dl:
                p["_deeplink_client_reuse"] = True
                continue
            urls_to_convert.append(clean_url)
            products_needing_api.append(p)
        else:
            p["_clean_url"] = ""

    reuse_n = sum(1 for p in products if isinstance(p, dict) and p.get("_deeplink_client_reuse"))
    logger.info(
        "deeplink_enrich channel_id=%s coupang_api_urls=%s client_reuse=%s",
        channel_id,
        len(urls_to_convert),
        reuse_n,
    )

    deeplink_map: dict[str, str] = {}
    failed_items: list[dict] = []
    coupang_api_called = False

    if urls_to_convert:
        if access_key and secret_key:
            try:
                deeplink_map = await generate_deeplinks(
                    urls_to_convert,
                    access_key,
                    secret_key,
                )
                coupang_api_called = True
                map_values = [str(v or "").strip() for v in deeplink_map.values()]
                map_samples = [
                    {"originalUrl": str(k)[:180], "shortenUrl": str(v)[:180]}
                    for k, v in list(deeplink_map.items())[:3]
                ]
                logger.info(
                    "deeplink_pipeline_api_result channel_id=%s mapped=%s mapped_url_kinds=%s map_samples=%s",
                    channel_id,
                    len(deeplink_map),
                    common.count_url_kinds(map_values),
                    map_samples,
                )
            except Exception as e:
                logger.exception(
                    "deeplink_generation_exception",
                    extra={
                        "channel_id": channel_id,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    },
                )
                failed_items = [
                    {
                        "productId": p.get("productId") or "",
                        "productName": p.get("productName") or "",
                        "reason": "api_error",
                    }
                    for p in products_needing_api
                ]
        else:
            logger.warning(
                "deeplink_generation_skipped_missing_keys",
                extra={"channel_id": channel_id},
            )
            failed_items = [
                {
                    "productId": p.get("productId") or "",
                    "productName": p.get("productName") or "",
                    "reason": "missing_api_keys",
                }
                for p in products_needing_api
            ]

    if urls_to_convert and not failed_items:
        for p in products_needing_api:
            clean_url = p.get("_clean_url", "")
            if not clean_url:
                continue
            if not deeplink_map.get(clean_url):
                failed_items.append({
                    "productId": p.get("productId") or "",
                    "productName": p.get("productName") or "",
                    "reason": "missing_from_api_response",
                })

    for p in products:
        if not isinstance(p, dict):
            continue
        clean_url = p.pop("_clean_url", "")
        pid = str(p.get("productId", ""))
        if p.pop("_deeplink_client_reuse", False):
            p.pop("subId", None)
            continue

        short_url = deeplink_map.get(clean_url, "")
        if not short_url and pid:
            for orig_url, s_url in deeplink_map.items():
                if pid in str(orig_url):
                    short_url = s_url
                    break
        p["deepLink"] = short_url
        if not short_url and clean_url:
            print(
                f"🚨 [경고] PID {pid} 딥링크 매칭 완전 실패! 쿠팡 API 응답을 확인하세요.",
                flush=True,
            )

    for p in products:
        if isinstance(p, dict):
            p.pop("subId", None)

    assigned_deeplinks = [str(p.get("deepLink") or "").strip() for p in products if isinstance(p, dict)]
    missing_ids = [
        str(p.get("productId") or "")
        for p in products
        if isinstance(p, dict) and not str(p.get("deepLink") or "").strip()
    ][:10]
    logger.info(
        "deeplink_pipeline_before_append channel_id=%s products=%s deepLink_kinds=%s missing_deeplink_product_ids=%s",
        channel_id,
        len(products),
        common.count_url_kinds(assigned_deeplinks),
        missing_ids,
    )

    return failed_items, mall_shop_url, coupang_api_called


@router.post("/deeplink-preview")
async def sheets_deeplink_preview(
    request: Request,
    body: SheetSendBody,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """시트 전송 전 딥링크 미리보기. 시트/쿠팡 키 없어도 채널·DB만으로 몰 URL을 돌려줄 수 있다."""
    from ..channels import get_channels
    from ..services.mall_tracking import mall_shop_url_for_channel

    channel = next((c for c in get_channels() if c.get("channel_id") == body.channel_id), None)
    if not channel:
        return JSONResponse(status_code=404, content={"error": "channel not found"})

    mall_shop_url = mall_shop_url_for_channel(channel, db=db, request=request)

    if not body.products:
        return {
            "ok": True,
            "status": "empty",
            "mall_shop_url": mall_shop_url,
            "products": [],
            "failed_count": 0,
            "failed_items": [],
            "coupang_api_called": False,
        }

    products = [dict(x) if isinstance(x, dict) else {} for x in body.products]

    try:
        failed_items, mall_shop_url, coupang_called = await _enrich_products_with_deeplinks(
            request=request,
            channel=channel,
            channel_id=body.channel_id,
            products=products,
            db=db,
        )
    except Exception as e:
        logger.exception("deeplink_preview_error channel_id=%s", body.channel_id)
        return JSONResponse(status_code=502, content={"error": str(e)})

    if failed_items:
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "status": "deeplink_required",
                "error": (
                    "딥링크 생성에 실패한 상품이 있습니다. "
                    "쿠팡 API 키·응답을 확인한 뒤 다시 시도하세요."
                ),
                "mall_shop_url": mall_shop_url,
                "failed_count": len(failed_items),
                "failed_items": failed_items,
            },
        )

    return {
        "ok": True,
        "status": "success",
        "mall_shop_url": mall_shop_url,
        "products": products,
        "failed_count": 0,
        "failed_items": [],
        "coupang_api_called": coupang_called,
    }


@router.post("/send")
async def sheets_send(
    request: Request,
    body: SheetSendBody,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """확정 상품을 채널 구글 시트에 추가. F열(쿠팡 URL) 기준 중복은 제외 후 Append."""
    from ..channels import get_channels
    from ..services.google_sheets import (
        append_rows,
        build_rows,
        get_existing_values,
        notify_product_delivery_webapp,
    )

    channel = next((c for c in get_channels() if c.get("channel_id") == body.channel_id), None)
    if not channel:
        return JSONResponse(status_code=404, content={"error": "channel not found"})
    sheet_id = (channel.get("google_sheet_id") or "").strip()
    tab_name = (channel.get("sheet_tab_name") or "상품목록").strip()
    if not sheet_id:
        return _missing_google_sheet_response(body.channel_id)
    if not body.products:
        return {
            "ok": True,
            "status": "success",
            "message": "전송할 상품이 없습니다.",
            "failed_count": 0,
            "failed_items": [],
        }

    try:
        existing_urls = await get_existing_values(sheet_id, tab_name, column="F")
        new_products = [
            p for p in body.products
            if (p.get("productUrl") or "").strip() not in existing_urls
        ]
        input_urls = [
            (p.get("productUrl") or "").strip()
            for p in body.products
            if isinstance(p, dict)
        ]
        logger.info(
            "deeplink_pipeline_input channel_id=%s received=%s deduped=%s existing_f_urls=%s input_url_kinds=%s input_url_samples=%s",
            body.channel_id,
            len(body.products),
            len(new_products),
            len(existing_urls),
            common.count_url_kinds(input_urls),
            common.sample_urls(input_urls),
        )
        if not new_products:
            return {
                "ok": True,
                "status": "duplicate",
                "message": "전부 중복된 상품입니다.",
                "failed_count": 0,
                "failed_items": [],
            }

        failed_items, mall_shop_url, _coupang_called = await _enrich_products_with_deeplinks(
            request=request,
            channel=channel,
            channel_id=body.channel_id,
            products=new_products,
            db=db,
        )

        if failed_items:
            logger.warning(
                "deeplink_pipeline_blocked_append channel_id=%s failed_count=%s reasons=%s",
                body.channel_id,
                len(failed_items),
                sorted({str(item.get("reason") or "") for item in failed_items}),
            )
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "status": "deeplink_required",
                    "error": (
                        "딥링크가 누락된 상품이 있어 시트 전송을 중단했습니다. "
                        "외부 게시 전 딥링크를 모두 확인하세요."
                    ),
                    "failed_count": len(failed_items),
                    "failed_items": failed_items,
                },
            )

        rows = build_rows(new_products, channel_id=body.channel_id)
        await append_rows(sheet_id, tab_name, rows)

        delivery_url = (channel.get("product_delivery_url") or "").strip()
        if delivery_url:
            products_payload = [
                {
                    "productId": p.get("productId"),
                    "productName": p.get("productName"),
                    "productUrl": p.get("productUrl"),
                    "deepLink": p.get("deepLink"),
                    "price": p.get("price"),
                    "imageUrl": p.get("imageUrl"),
                    "category": p.get("category"),
                    "videoNo": p.get("videoNo"),
                }
                for p in new_products
            ]
            await notify_product_delivery_webapp(
                delivery_url,
                {
                    "channel_id": body.channel_id,
                    "google_sheet_id": sheet_id,
                    "sheet_tab_name": tab_name,
                    "mall_shop_url": mall_shop_url,
                    "products": products_payload,
                    "sheet_rows": rows,
                },
            )

        n, m = len(body.products), len(new_products)
        k = n - m
        msg = f"총 {n}개 중 {m}개 전송 완료, {k}개 중복 제외되었습니다."
        return {
            "ok": True,
            "status": "success",
            "message": msg,
            "failed_count": len(failed_items),
            "failed_items": failed_items,
        }
    except FileNotFoundError as e:
        print("\033[91m[시트 전송 에러]\033[0m", str(e), flush=True)
        return JSONResponse(status_code=503, content={"error": str(e)})
    except Exception as e:
        print("\033[91m[시트 전송 에러]\033[0m", str(e), flush=True)
        return JSONResponse(status_code=502, content={"error": str(e)})


@router.get("/items")
async def get_sheets_items(
    channel_id: str = "",
    _: None = Depends(require_admin),
):
    """채널 시트의 등록 상품 목록(A~K) 조회. 첫 행은 헤더, 데이터는 row_index와 함께 반환."""
    from ..channels import get_channels
    from ..services.google_sheets import get_all_rows

    if not channel_id.strip():
        return JSONResponse(status_code=400, content={"error": "channel_id required"})
    channel = next((c for c in get_channels() if c.get("channel_id") == channel_id.strip()), None)
    if not channel:
        return JSONResponse(status_code=404, content={"error": "channel not found"})
    sheet_id = (channel.get("google_sheet_id") or "").strip()
    tab_name = (channel.get("sheet_tab_name") or "상품목록").strip()
    if not sheet_id:
        return _missing_google_sheet_response(channel_id)

    try:
        rows = await get_all_rows(sheet_id, tab_name, "A:K")
    except FileNotFoundError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})

    keys = ["no", "category", "productName", "price", "imageUrl", "productUrl", "deepLink", "videoNo", "status", "regDate", "subId"]
    items = []
    for index in range(1, len(rows)):
        row = rows[index]
        if not isinstance(row, list):
            continue
        # 행 길이 11 미만이면 빈 문자열로 패딩
        padded = (row + [""] * 11)[:11]
        item: dict[str, Any] = {"row_index": index + 1}
        for i, key in enumerate(keys):
            val = padded[i] if i < len(padded) else ""
            item[key] = "" if val is None else str(val).strip() if isinstance(val, str) else val
        items.append(item)
    return {"items": items}


class MallImportFromSheetBody(BaseModel):
    channel_id: str


@router.post("/mall-import")
async def post_mall_import_from_sheet(
    body: MallImportFromSheetBody,
    _: None = Depends(require_admin),
):
    """공개 몰은 DB가 아니라 시트 JSON API만 사용한다. 시트 행 수·몰 GET URL(전용 또는 전달 웹훅 URL 폴백) 설정만 점검한다."""
    from ..channels import get_channels
    from ..services.google_sheets import get_all_rows

    cid = body.channel_id.strip()
    if not cid:
        return JSONResponse(status_code=400, content={"error": "channel_id required"})
    channel = next((c for c in get_channels() if c.get("channel_id") == cid), None)
    if not channel:
        return JSONResponse(status_code=404, content={"error": "channel not found"})
    mall_slug = (channel.get("mall_pump_slug") or "").strip()
    if not mall_slug:
        return JSONResponse(
            status_code=400,
            content={
                "error": (
                    "채널에 mall_pump_slug 가 없습니다. "
                    "`.env`에 예: CHANNEL_201_MALL_PUMP_SLUG=인플루언서의 name_slug 를 넣으세요."
                ),
            },
        )
    api_url = (channel.get("mall_products_api_url") or "").strip()
    sheet_id = (channel.get("google_sheet_id") or "").strip()
    tab_name = (channel.get("sheet_tab_name") or "상품목록").strip()
    if not sheet_id:
        return _missing_google_sheet_response(cid)

    try:
        rows = await get_all_rows(sheet_id, tab_name, "A:K")
    except FileNotFoundError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})

    data_rows = max(0, len(rows) - 1)
    warn = None
    if not api_url:
        warn = (
            "몰 상품 GET URL이 없습니다. `CHANNEL_*_PRODUCT_DELIVERY_WEBAPP_URL` 또는 "
            "`CHANNEL_*_MALL_PRODUCTS_API_URL` 중 하나는 채워야 공개 몰에서 목록을 불러올 수 있습니다."
        )
    return {
        "ok": True,
        "inserted": 0,
        "sheet_rows": data_rows,
        "mall_products_api_configured": bool(api_url),
        "warning": warn,
    }


class SheetItemsStatusBody(BaseModel):
    channel_id: str
    updates: list[dict]


@router.post("/items/status")
async def post_sheets_items_status(
    body: SheetItemsStatusBody,
    _: None = Depends(require_admin),
):
    """선택한 행의 I열(게시상태)을 일괄 수정."""
    from ..channels import get_channels
    from ..services.google_sheets import batch_update_cells

    if not body.channel_id.strip():
        return JSONResponse(status_code=400, content={"error": "channel_id required"})
    channel = next((c for c in get_channels() if c.get("channel_id") == body.channel_id.strip()), None)
    if not channel:
        return JSONResponse(status_code=404, content={"error": "channel not found"})
    sheet_id = (channel.get("google_sheet_id") or "").strip()
    tab_name = (channel.get("sheet_tab_name") or "상품목록").strip()
    if not sheet_id:
        return _missing_google_sheet_response(body.channel_id)

    if " " in tab_name or "'" in tab_name:
        range_fmt = f"'{tab_name}'!I{{0}}"
    else:
        range_fmt = f"{tab_name}!I{{0}}"

    data = []
    for u in body.updates or []:
        row_index = u.get("row_index")
        new_status = u.get("new_status", "")
        if row_index is None:
            continue
        data.append({
            "range": range_fmt.format(row_index),
            "values": [[str(new_status)]],
        })

    if not data:
        return {"ok": True, "message": "변경할 항목이 없습니다."}

    try:
        await batch_update_cells(sheet_id, data)
        return {"ok": True, "message": "상태 변경 완료"}
    except Exception as e:
        print("\033[91m[시트 상태 변경 에러]\033[0m", str(e), flush=True)
        return JSONResponse(status_code=502, content={"error": str(e)})
