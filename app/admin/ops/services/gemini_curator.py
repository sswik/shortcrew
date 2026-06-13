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


# ── 브리지 하이브리드 선택기 (P2): 베스트/골드박스 후보 N개 → 주제 연관 1개 ──

class ProductPick(BaseModel):
    relevant: bool = Field(description="후보 중 주제와 충분히 연관된 상품이 있으면 true, 없으면 false")
    picked_index: int = Field(description="선정 상품의 0-기반 인덱스. relevant=false 면 -1")
    selection_reason: str = Field(description="해당 주제/페르소나에 왜 맞는지 큐레이터 톤 1~2줄. relevant=false 면 연관 상품이 없는 이유")


def _candidate_line(i: int, p: dict) -> str:
    name = str(p.get("productName") or "").strip()
    price = p.get("price")
    cat = str(p.get("category") or "").strip()
    extra = f", {cat}" if cat else ""
    price_str = f"₩{price}" if price not in (None, "", 0) else "가격미상"
    return f"{i}. {name} ({price_str}{extra})"


async def pick_product_for_topic(
    api_key: str,
    *,
    topic: str,
    candidates: list[dict],
    persona: str = "",
    temperature: float = 0.3,
) -> dict:
    """베스트/골드박스 후보(coupang fetch 결과) N개 중 주제와 가장 연관된 1개를 Gemini가 선정.

    반환: ``{"relevant": bool, "picked": dict|None, "selection_reason": str}``.
    주제와 맞는 상품이 없으면 relevant=False — 호출부는 기존 '자막→키워드' 경로로 강등한다.
    """
    if not api_key:
        raise ValueError("Gemini API 키가 설정되지 않았습니다.")
    if not candidates:
        return {"relevant": False, "picked": None, "selection_reason": "후보 상품이 없습니다."}

    client = genai.Client(api_key=api_key)
    who = (persona or "이커머스 상품 큐레이터").strip()
    system_instruction = (
        f"당신은 '{who}' 입니다. 주어진 후보 상품 목록에서 지정된 '주제'와 가장 연관성이 높고 "
        "그 페르소나가 자연스럽게 추천할 수 있는 상품 1개만 고릅니다. "
        "주제와 무관하거나 억지로 끼워맞춰야 하는 상품뿐이면 relevant=false 로 정직하게 답하세요. "
        "절대 무관한 상품을 골라 연관성을 지어내지 마세요."
    )
    lines = "\n".join(_candidate_line(i, p) for i, p in enumerate(candidates))
    prompt = (
        f"[주제]\n{topic.strip()}\n\n"
        f"[후보 상품]\n{lines}\n\n"
        "위 후보 중 주제와 가장 맞는 상품 1개의 인덱스를 고르고, 선정 이유를 큐레이터 톤으로 1~2줄 쓰세요. "
        "적합한 상품이 없으면 relevant=false, picked_index=-1."
    )

    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=ProductPick,
            temperature=temperature,
        ),
    )
    data = json.loads(response.text or "{}")
    idx = data.get("picked_index", -1)
    reason = (data.get("selection_reason") or "").strip()
    if not data.get("relevant") or not isinstance(idx, int) or idx < 0 or idx >= len(candidates):
        return {"relevant": False, "picked": None, "selection_reason": reason or "연관 상품 없음"}
    return {"relevant": True, "picked": candidates[idx], "selection_reason": reason}


# ── 자동 DM 문구 생성 (브리지 큐레이션의 auto_dm) ──

async def generate_dm_message(
    api_key: str,
    *,
    product_title: str,
    deeplink: str,
    persona: str = "",
    temperature: float = 0.7,
) -> str:
    """인스타 댓글 답변으로 보낼 자동 DM 문구 1개를 생성(평문 반환)."""
    if not api_key:
        raise ValueError("Gemini API 키가 설정되지 않았습니다.")
    who = (persona or "상품 큐레이터").split("(", 1)[0].strip()
    client = genai.Client(api_key=api_key)
    prompt = (
        f"당신은 인플루언서 '{who}'입니다. 인스타 댓글을 남긴 분께 답으로 보낼 DM 문구를 쓰세요.\n"
        f"[상품] {product_title}\n[구매 링크] {deeplink}\n"
        "조건: 친근한 존댓말 2~3문장, 과장광고·수치과장 금지, 끝에 구매 링크 1개 포함, "
        "이모지 1개 정도, 200자 이내. 문구 텍스트만 출력."
    )
    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=temperature),
    )
    return (response.text or "").strip()
