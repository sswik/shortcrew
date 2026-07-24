"""Gemini로 쇼츠 대본(제목·대본·설명·장면 프롬프트) 생성.

인플루언서 커머스 채널(골프/테니스/쇼핑)용. 상품과 '실제 후기'가 있으면
그 후기를 근거로 1인칭 사용후기 대본을, 없으면 상품군 추천형(폴백) 대본을 만든다.
출력 스키마는 AFxx 발행 파이프라인이 읽는 `시트1` 컬럼과 1:1 대응한다.

- 후기 기반: reviews.content(인플루언서가 직접 쓴 소감)를 사실 근거로 삼아 과장 없이 재구성.
- 폴백: 후기 없으면 인플루언서가 직접 써본 것처럼 1인칭 경험담(검증 불가 수치·성능 단정은 금지, 주관적 사용감 위주).
- 딥링크·구매유도는 대본 본문이 아니라 '설명'에만(정책: 딥링크는 설명/댓글/DM).
"""

from __future__ import annotations

import json

from google import genai
from google.genai import types
from pydantic import BaseModel, Field


class ShortsScriptResult(BaseModel):
    topic: str = Field(description="영상 주제 한 줄(내부 관리용). 30자 이내.")
    title: str = Field(description="영상 제목. 40자 이내, 클릭을 부르는 존댓말 한국어.")
    script: str = Field(
        description="대본 본문. 350~400자, 해요체(~해요/~죠/~거든요). "
        "첫 문장은 충격 사실 또는 반전 질문으로. 인사/예고 표현 금지. "
        "구매유도·링크·할인 문구는 넣지 말 것(설명에서 처리)."
    )
    description: str = Field(
        description="유튜브 등록 설명. 2~3문장 + 해시태그 3~5개. 여기에만 상품 안내를 둔다."
    )
    video_length: str = Field(description="예상 영상 길이. 예: '0:50'")
    scene1_prompt: str = Field(description="장면1 이미지 생성 프롬프트(한국어, 제품/상황 묘사).")
    scene2_prompt: str = Field(description="장면2 이미지 생성 프롬프트.")
    scene3_prompt: str = Field(description="장면3 이미지 생성 프롬프트.")
    scene4_prompt: str = Field(description="장면4 이미지 생성 프롬프트.")
    scene5_prompt: str = Field(description="장면5 이미지 생성 프롬프트.")


_COMMON_RULES = (
    "[공통 규칙 — 반드시 준수]\n"
    "1. 말투는 존댓말 해요체로 일관되게. 반말·평서문 종결(~이다/~한다/~다) 금지.\n"
    "2. 첫 문장은 충격적 사실 또는 반전 질문으로 시작(첫 6단어 안에 호기심 갭). "
    "'여러분', '오늘은', '소개합니다', '알아보겠습니다' 같은 인사/예고 시작 금지.\n"
    "3. 수치 비교/비율('~의 N배', '~분의 1')·'세계 최초'·'유일한' 같은 단정 표현 금지"
    "(팩트체크 불가 할루시네이션 방지).\n"
    "4. 소수점 수치를 임의 생성하지 말 것.\n"
    "5. 대본 본문에 '최저가/지금 구매/링크 클릭/할인' 같은 노골적 광고 문구 금지. "
    "구매 안내는 description 에만.\n"
)


async def generate_shorts_script(
    api_key: str,
    *,
    influencer_display: str,
    field_kr: str,
    product_title: str,
    product_price: float,
    product_url: str,
    image_url: str,
    category: str = "",
    review_content: str = "",
) -> dict:
    """상품(+선택적 후기)으로 쇼츠 대본 1편을 생성. review_content 있으면 후기형, 없으면 폴백형."""
    client = genai.Client(api_key=api_key)
    review = (review_content or "").strip()

    if review:
        mode_block = (
            "[모드: 실제 사용후기 기반 1인칭]\n"
            f"아래는 이 인플루언서({influencer_display})가 '{product_title}'을(를) 직접 써보고 남긴 "
            "실제 후기입니다. 이 후기의 사실·경험만을 근거로, 본인이 말하는 1인칭 쇼츠 대본으로 "
            "자연스럽게 재구성하세요. 후기에 없는 성능·수치를 지어내지 마세요.\n"
            f"---\n{review}\n---\n"
        )
    else:
        mode_block = (
            "[모드: 후기 없음 — 인플루언서가 직접 써본 것처럼 1인칭 경험담]\n"
            f"이 인플루언서({influencer_display})가 **이 상품 '{product_title}'을(를) 직접 사서 써본 것처럼** "
            "1인칭 사용 경험담 대본을 쓰세요. 처음 써봤을 때의 느낌, 실제 쓰는 상황, 좋았던 점을 "
            "본인 경험처럼 생생하게. 대본은 처음부터 끝까지 **오직 이 상품 하나**에 대해서만 — "
            f"'{field_kr} 분야 일반'이나 다른 상품으로 새지 마세요.\n"
            "단, 진짜 후기 데이터가 없으므로 **검증 불가한 수치·성능 단정(예: '2배 더 오래간다', "
            "'변색 절대 없음', 구체적 스펙)은 지어내지 말고**, '써보니 손에 잘 맞더라'·'생각보다 "
            "튼튼한 느낌'처럼 주관적 사용감·상황 위주로 자연스럽게 쓰세요.\n"
        )

    prompt = (
        f"당신은 인스타 릴스/유튜브 쇼츠 {field_kr} 쇼핑추천 채널 '{influencer_display}'의 전문 대본 작가입니다.\n\n"
        f"[상품 정보]\n"
        f"- 상품명: {product_title}\n"
        f"- 카테고리: {category or field_kr}\n"
        f"- 가격(원): {product_price}\n"
        f"- 대표 이미지 URL: {image_url}\n\n"
        f"{mode_block}\n"
        f"{_COMMON_RULES}\n"
        "위 정보로 45~60초 쇼츠 1편의 대본 세트를 생성하세요. "
        "장면 프롬프트 5개는 대본 흐름에 맞춰 제품과 사용 상황을 시각적으로 묘사하세요."
    )

    try:
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "당신은 이커머스 숏폼 대본 작가입니다. 출력은 지정된 JSON 스키마만 따르세요."
                ),
                response_mime_type="application/json",
                response_schema=ShortsScriptResult,
                temperature=0.75,
            ),
        )
        raw = (response.text or "").strip()
        data = json.loads(raw)
        return ShortsScriptResult.model_validate(data).model_dump()
    except Exception as e:
        print(f"Gemini 쇼츠 대본 호출 에러: {e}")
        raise
