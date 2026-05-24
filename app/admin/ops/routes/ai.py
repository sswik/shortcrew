"""Gemini 키워드 큐레이션·히스토리 시트 기록·리뷰 초안."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.auth import require_admin
from app.admin.deps import get_db
from app.admin.ops.routes import common
from models import Influencer, Product

router = APIRouter()


class CurateBody(BaseModel):
    channel_id: str
    keywords: list[str] = []
    seed_keywords: list[dict] = []
    custom_prompt: str = ""  # 프론트엔드 입력창(지시사항, 예: 5만원 이하 등) 내용


@router.post("/curate")
async def ai_curate_trends(
    request: Request,
    body: CurateBody,
    _: None = Depends(require_admin),
):
    """프론트엔드에서 20개 키워드를보내면 Gemini가 3개로 압축해서 돌려줍니다."""
    api_key = common.get_env_secret(request, "GOOGLE_GEMINI_KEY")
    if not api_key:
        return JSONResponse(
            status_code=503,
            content={"error": "서버에 GOOGLE_GEMINI_KEY가 설정되지 않았습니다."}
        )

    from app.admin.ops.channels import get_channels

    channel = next((c for c in get_channels() if c.get("channel_id") == body.channel_id), None)
    channel_name = channel.get("name") if channel else "쇼핑"
    if not channel:
        return JSONResponse(status_code=404, content={"error": "channel not found"})

    keywords = [str(k).strip() for k in (body.keywords or []) if str(k).strip()]
    if body.seed_keywords:
        extracted = []
        for item in body.seed_keywords:
            if not isinstance(item, dict):
                continue
            kw = str(item.get("keyword") or "").strip()
            if kw:
                extracted.append(kw)
        if extracted:
            keywords = extracted

    if not keywords:
        raw = channel.get("naver_category_id") or "50000000"
        category_ids = [raw] if isinstance(raw, str) else list(raw) if raw else ["50000000"]
        trend_keywords = channel.get("trend_keywords") or []
        settings = common.load_channel_settings()
        channel_settings = settings.get(body.channel_id) or {}
        monitor_keywords = channel_settings.get("monitor_keywords")
        if monitor_keywords is None:
            monitor_keywords = channel.get("monitor_keywords") or []

        naver_client_id = common.get_env_secret(request, "NAVER_CLIENT_ID")
        naver_client_secret = common.get_env_secret(request, "NAVER_CLIENT_SECRET")
        if not naver_client_id or not naver_client_secret:
            return JSONResponse(status_code=503, content={"error": "NAVER API 키가 설정되지 않았습니다."})
        coupang_access_key = common.get_env_secret(request, "COUPANG_ACCESS_KEY")
        coupang_secret_key = common.get_env_secret(request, "COUPANG_SECRET_KEY")

        from app.admin.ops.services.naver_datalab import get_naver_trend_two_track

        trend_result = await get_naver_trend_two_track(
            naver_client_id,
            naver_client_secret,
            category_ids,
            trend_keywords,
            monitor_keywords,
            coupang_access_key=coupang_access_key,
            coupang_secret_key=coupang_secret_key,
            target_count=20,
        )
        keywords = [str(item.get("keyword") or "").strip() for item in trend_result.get("seed_keywords", []) if str(item.get("keyword") or "").strip()]
        if not keywords:
            return JSONResponse(status_code=400, content={"error": "큐레이션할 시드 키워드를 생성하지 못했습니다."})

    from app.admin.ops.services.gemini_curator import curate_keywords_with_gemini

    try:
        result = await curate_keywords_with_gemini(api_key, channel_name, keywords, body.custom_prompt)
    except Exception as e:
        print(f"\n [Gemini AI 에러] 상세 원인: {e}\n")
        return JSONResponse(status_code=502, content={"error": str(e)})

    return {
        **result,
        "used_seed_keywords": keywords,
    }


class CurateHistorySendBody(BaseModel):
    channel_id: str
    custom_prompt: str
    items: list[dict]


@router.post("/curate/send-to-history-sheet")
async def send_curation_to_history_sheet(
    request: Request,
    body: CurateHistorySendBody,
    _: None = Depends(require_admin),
):
    """AI 추천 결과를 'AI 기록 시트'로 수동 전송합니다."""
    from app.admin.ops.channels import get_channels

    channel = next((c for c in get_channels() if c.get("channel_id") == body.channel_id), None)

    if not channel:
        return JSONResponse(status_code=404, content={"error": "채널을 찾을 수 없습니다."})

    history_id = (channel.get("history_sheet_id") or "").strip()
    history_tab = (channel.get("history_sheet_tab") or "").strip()

    if not history_id or not history_tab:
        return JSONResponse(status_code=400, content={"error": "이 채널은 히스토리 시트가 설정되지 않았습니다."})

    from app.admin.ops.services.google_sheets import append_rows, build_history_rows

    try:
        rows = build_history_rows(body.items, body.custom_prompt)
        await append_rows(history_id, history_tab, rows, column_range="A:F")
        return {"ok": True, "message": "AI 큐레이션 기록이 시트에 저장되었습니다."}
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


class ReviewDraftBody(BaseModel):
    product_id: int = Field(ge=1, description="연동할 상품 PK")
    influencer_slug: str = Field(min_length=1, max_length=100)
    extra_instruction: str = ""


@router.post("/review-draft")
async def ai_review_draft(
    request: Request,
    body: ReviewDraftBody,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """연결 상품·인플루언서 맥락으로 리뷰 제목·HTML 본문 초안을 생성합니다."""
    api_key = common.get_env_secret(request, "GOOGLE_GEMINI_KEY")
    if not api_key:
        return JSONResponse(
            status_code=503,
            content={"error": "서버에 GOOGLE_GEMINI_KEY가 설정되지 않았습니다."},
        )

    product = db.scalar(select(Product).where(Product.id == body.product_id))
    if not product:
        return JSONResponse(status_code=404, content={"error": "상품을 찾을 수 없습니다."})

    inf = db.scalar(select(Influencer).where(Influencer.name_slug == body.influencer_slug))
    influencer_display = inf.display_name if inf else body.influencer_slug

    from app.admin.ops.services.gemini_review_draft import generate_review_draft

    try:
        result = await generate_review_draft(
            api_key,
            influencer_display=influencer_display,
            influencer_slug=body.influencer_slug,
            product_title=product.title,
            product_price=float(product.price),
            product_url=product.coupang_url or "",
            image_url=product.image_url or "",
            extra_instruction=body.extra_instruction,
        )
    except Exception as e:
        print(f"\n [Gemini 리뷰 초안 에러] {e}\n")
        return JSONResponse(status_code=502, content={"error": str(e)})

    return result
