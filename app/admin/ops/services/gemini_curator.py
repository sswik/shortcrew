"""Gemini 2.5 Flash를 활용한 트렌드 큐레이션 엔진 (구조화된 출력 적용)."""
from __future__ import annotations
import json
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# 1. AI가 무조건 지켜야 하는 '출력 법률(Schema)'을 정의합니다.
class CuratedItem(BaseModel):
    original_keyword: str = Field(description="네이버 트렌드에서 선택한 원본 키워드")
    reason: str = Field(description="숏폼 영상(릴스, 쇼츠)으로 제작 시 바이럴 및 판매 가능성이 높은 이유 (핵심만 1~2줄)")
    coupang_search_query: str = Field(description="쿠팡에서 이 상품을 소싱할 때 입력할 구체적이고 정확한 검색어")

class CurationResult(BaseModel):
    items: list[CuratedItem] = Field(description="최종 선정된 3개의 큐레이션 아이템 목록")

async def curate_keywords_with_gemini(
    api_key: str, channel_name: str, keywords: list[str], custom_prompt: str = ""
) -> dict:
    """정제된 시드 키워드를 받아 Gemini가 숏폼용 3개로 큐레이션합니다."""
    if not api_key:
        raise ValueError("Gemini API 키가 설정되지 않았습니다.")
    if not keywords:
        return {"items": []}

    # 최신 SDK 클라이언트 초기화
    client = genai.Client(api_key=api_key)
    
    # 2. AI 페르소나 부여
    system_instruction = (
        f"당신은 '{channel_name}' 채널을 운영하는 대한민국 최고 등급의 이커머스 숏폼 콘텐츠 디렉터입니다. "
        "당신의 목표는 주어진 실시간 검색어 중에서 틱톡, 릴스, 쇼츠에서 '시각적인 어그로'를 끌기 좋고 "
        "실제 구매 전환율이 폭발할 만한 상품 키워드 딱 3개만 엄선하는 것입니다. "
        "추상적이거나, 브랜드 이름만 있거나, 영상으로 보여주기 힘든 키워드는 무조건 배제하세요."
    )
    
    # 3. 실제 던질 질문 (대표님 특별 지시사항이 있으면 프롬프트에 포함)
    seed_lines = "\n".join([f"- {kw}" for kw in keywords])
    prompt = (
        "아래는 데이터 파이프라인에서 정제된 시드 키워드 목록입니다.\n"
        f"{seed_lines}\n\n"
        "위 시드 중 숏폼 커머스 전환율이 가장 높은 3개를 골라주세요."
    )
    if (custom_prompt or "").strip():
        prompt += f"\n\n[추가 지시사항] 반드시 반영해 주세요: {custom_prompt.strip()}"

    try:
        # 비동기(aio) 방식으로 Gemini 2.5 Flash 호출
        response = await client.aio.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json", # JSON으로만 대답해!
                response_schema=CurationResult,        # 위에서 만든 규격대로 대답해!
                temperature=0.7,                       # 창의성과 논리성의 황금비율
            ),
        )
        # 응답된 JSON 문자열을 파이썬 딕셔너리로 변환하여 반환
        return json.loads(response.text)
    except Exception as e:
        print(f"Gemini 호출 에러: {e}")
        raise e
