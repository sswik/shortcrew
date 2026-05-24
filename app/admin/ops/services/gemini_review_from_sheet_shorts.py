"""Gemini: 시트 매칭 쇼츠 자막 + 상품명 + 딥링크 → 리뷰 제목·HTML."""

from __future__ import annotations

import html
import json

from google import genai
from google.genai import types
from pydantic import BaseModel, Field


class SheetShortsReviewDraft(BaseModel):
    title: str = Field(description="리뷰 제목. 80자 이내 한국어.")
    html: str = Field(
        description="리뷰 본문 HTML. p, h2, h3, ul, li, strong, em, br 만 사용. script/style/onclick 금지."
    )


class ShortsProductPick(BaseModel):
    keyword: str = Field(description="쿠팡 검색에 사용할 상품 키워드 1개")


def append_deeplink_tail(html_content: str, deeplink: str, anchor_text: str = "쿠팡에서 구매하기") -> str:
    """본문 끝에 G열 딥링크 CTA 한 블록(이미 동일 URL이 있으면 생략)."""
    dl = (deeplink or "").strip()
    if not dl:
        return (html_content or "").strip()
    h = (html_content or "").strip()
    if dl in h:
        return h
    safe = html.escape(dl, quote=True)
    at = html.escape(anchor_text, quote=True)
    tail = (
        f'<p class="shorts-review-cta">'
        f'<a href="{safe}" target="_blank" rel="noopener noreferrer">{at}</a>'
        f"</p>"
    )
    if not h:
        return tail
    return h + "\n" + tail


async def generate_review_from_sheet_transcript(
    api_key: str,
    *,
    influencer_display: str,
    transcript_text: str,
    product_name: str,
    deeplink: str,
) -> dict:
    """자막(또는 제목·설명) 기반 홍보 톤 사용후기 HTML."""
    client = genai.Client(api_key=api_key)
    t = (transcript_text or "").strip()
    if len(t) > 12000:
        t = t[:12000] + "\n…(이하 생략)"
    prompt = (
        f"인플루언서 표시명: {influencer_display}\n"
        f"시트 상품명: {product_name}\n"
        f"구매 딥링크(URL, 본문에 직접 넣지 말 것): {deeplink}\n\n"
        f"다음은 해당 상품 쇼츠 영상에서 추출한 말(자막 또는 제목·설명)입니다:\n---\n{t}\n---\n\n"
        "위 내용을 바탕으로 **한국어 사용후기**를 작성하세요.\n"
        "- 톤: 홍보 느낌이 나되 과장 광고 문구·허위 체험은 피하고 진정성 있게.\n"
        "- 본문은 **유효한 HTML**만 (태그 열고 닫기). 마크다운 금지.\n"
        "- script, iframe, object, embed, style 태그 및 onclick 등 이벤트 속성 금지.\n"
        "- **구매 링크는 본문에 넣지 마세요.** (시스템이 마지막에 한 번만 붙입니다.)\n"
        "- 길이: 본문 HTML 기준 대략 400~1500자 분량.\n"
    )
    try:
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "당신은 이커머스 쇼츠·개인 몰용 사용후기 카피라이터입니다. "
                    "출력은 지정된 JSON 스키마만 따르세요."
                ),
                response_mime_type="application/json",
                response_schema=SheetShortsReviewDraft,
                temperature=0.7,
            ),
        )
        raw = (response.text or "").strip()
        data = json.loads(raw)
        draft = SheetShortsReviewDraft.model_validate(data)
        html_out = append_deeplink_tail(draft.html, deeplink)
        return {"title": draft.title.strip(), "html": html_out}
    except Exception as e:
        print(f"Gemini sheet-shorts review error: {e}")
        raise


async def pick_product_keyword_from_transcript(
    api_key: str,
    *,
    transcript_text: str,
    hinted_product_name: str,
) -> str:
    """자막에서 쿠팡 검색 키워드 1개를 뽑는다."""
    client = genai.Client(api_key=api_key)
    t = (transcript_text or "").strip()
    if len(t) > 8000:
        t = t[:8000] + "\n…(이하 생략)"
    prompt = (
        f"시트 기획 상품명(힌트): {hinted_product_name}\n\n"
        f"쇼츠 자막/설명:\n---\n{t}\n---\n\n"
        "위 내용을 보고 쿠팡에서 실제 상품 검색에 적합한 한국어 키워드 1개만 뽑아주세요. "
        "브랜드/핵심제품명 위주로 4~30자 내로 작성하세요."
    )
    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction="출력은 JSON 스키마만 따르세요.",
            response_mime_type="application/json",
            response_schema=ShortsProductPick,
            temperature=0.2,
        ),
    )
    raw = (response.text or "").strip()
    data = json.loads(raw)
    pick = ShortsProductPick.model_validate(data)
    return (pick.keyword or hinted_product_name or "").strip()
