"""Gemini로 상품 기반 리뷰 초안(제목 + HTML 본문) 생성."""

from __future__ import annotations

import json

from google import genai
from google.genai import types
from pydantic import BaseModel, Field


class ReviewDraftResult(BaseModel):
    title: str = Field(description="리뷰 제목. 80자 이내, 클릭을 부르는 한국어.")
    html: str = Field(
        description="리뷰 본문 HTML. p, h2, h3, ul, li, strong, em, br 정도만 사용. script/style/onclick 금지."
    )


async def generate_review_draft(
    api_key: str,
    *,
    influencer_display: str,
    influencer_slug: str,
    product_title: str,
    product_price: float,
    product_url: str,
    image_url: str,
    extra_instruction: str = "",
) -> dict:
    """상품·인플루언서 맥락으로 숏폼/몰 리뷰용 HTML 초안을 만든다."""
    client = genai.Client(api_key=api_key)
    extra = (extra_instruction or "").strip()
    prompt = (
        f"인플루언서 표시명: {influencer_display} (slug: {influencer_slug})\n"
        f"상품명: {product_title}\n"
        f"가격(원): {product_price}\n"
        f"대표 이미지 URL: {image_url}\n"
        f"구매/상품 페이지 URL: {product_url}\n\n"
        "위 상품을 이 인플루언서가 실제로 써본 것처럼 자연스러운 **한국어 리뷰**를 작성하세요.\n"
        "- 톤: 친근하지만 과장 광고 문구는 피할 것.\n"
        "- 본문은 반드시 **유효한 HTML 문자열**만 (태그 열고 닫기). 마크다운 금지.\n"
        "- script, iframe, object, embed, style 태그 및 onclick 등 이벤트 속성 금지.\n"
        "- 이미지는 필요 시 한 장만 `<img src=\"...\" alt=\"...\" />` 로 넣어도 됨(제공된 image URL 사용 가능).\n"
        "- 길이: 본문 HTML 기준 대략 400~1200자 분량.\n"
    )
    if extra:
        prompt += f"\n[추가 지시]\n{extra}\n"

    try:
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "당신은 이커머스 숏폼·개인 몰용 리뷰 카피라이터입니다. "
                    "출력은 지정된 JSON 스키마만 따르세요."
                ),
                response_mime_type="application/json",
                response_schema=ReviewDraftResult,
                temperature=0.75,
            ),
        )
        raw = (response.text or "").strip()
        data = json.loads(raw)
        return ReviewDraftResult.model_validate(data).model_dump()
    except Exception as e:
        print(f"Gemini 리뷰 초안 호출 에러: {e}")
        raise
