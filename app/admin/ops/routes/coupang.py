"""쿠팡 검색 API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.admin.auth import require_admin
from app.admin.ops.routes import common

router = APIRouter()


@router.get("/search")
async def coupang_search(
    request: Request,
    keyword: str = "",
    limit: int = 10,
    _: None = Depends(require_admin),
):
    """쿠팡 상품 검색(필터: 리뷰>=50, 평점>=4.5)."""
    if not keyword.strip():
        return {"products": [], "requested_limit": 0, "returned_count": 0, "error": "keyword required"}

    access_key = common.get_env_secret(request, "COUPANG_ACCESS_KEY")
    secret_key = common.get_env_secret(request, "COUPANG_SECRET_KEY")

    if not access_key or not secret_key:
        return JSONResponse(
            status_code=503,
            content={"error": "Coupang API keys not configured", "products": [], "requested_limit": 0, "returned_count": 0},
        )

    from app.admin.ops.services.coupang import search_products

    try:
        requested_limit = max(1, min(int(limit or 10), 50))
        outcome = await search_products(keyword.strip(), access_key, secret_key, limit=requested_limit)
        products = outcome.products
        return {
            "products": products,
            "requested_limit": requested_limit,
            "returned_count": len(products),
            "raw_collected": outcome.raw_collected,
            "filtered_count": outcome.filtered_count,
            "stop_reason": outcome.stop_reason,
            "queries_run": outcome.queries_run,
        }
    except Exception as e:
        print(f"\n🚨 [쿠팡 검색 에러] 🚨\n- 검색어: '{keyword}'\n- 에러 상세 원인: {e}\n")

        return JSONResponse(
            status_code=502,
            content={"error": str(e), "products": []},
        )
