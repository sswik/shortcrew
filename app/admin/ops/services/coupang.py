"""쿠팡 파트너스 API: HMAC-SHA256 서명 및 상품 검색·필터링."""
from __future__ import annotations

import hashlib
import hmac as hmacc
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)


def _url_kind(url: str) -> str:
    value = (url or "").strip().lower()
    if not value:
        return "empty"
    if "link.coupang.com/" in value:
        return "short"
    if "coupang.com/vp/" in value:
        return "vp"
    return "other"


def _count_url_kinds(urls: list[str]) -> dict[str, int]:
    counts = {"short": 0, "vp": 0, "other": 0, "empty": 0}
    for url in urls:
        counts[_url_kind(url)] += 1
    return counts


# 필터 기준값
MIN_REVIEWS = 50
MIN_RATING = 4.5

# 파트너스 상품 검색: 환경/계정별 limit 허용 범위 편차가 있어 보수값 20 사용.
# (50 사용 시 "limit is out of range"가 실제로 발생함)
COUPANG_SEARCH_PER_CALL_LIMIT = 20
COUPANG_SEARCH_MAX_PAGES = 10


def _gmt_now() -> str:
    """GMT 현재 시각을 yyMMddTHHmmssZ 형식으로 반환."""
    return datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")


def make_hmac_signature(secret_key: str, message: str) -> str:
    """secret_key로 message의 HMAC-SHA256 계산 후 hexdigest 반환."""
    return hmacc.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def build_authorization_header(
    access_key: str,
    secret_key: str,
    path: str,
    query: str,
    method: str = "GET",
) -> str:
    """쿠팡 API용 CEA Authorization 헤더 생성. (서명 시 path와 query 사이 물음표 제외)"""
    datetime_str = _gmt_now()
    message = datetime_str + method + path + query
    signature = make_hmac_signature(secret_key, message)
    return f"CEA algorithm=HmacSHA256, access-key={access_key}, signed-date={datetime_str}, signature={signature}"


def _apply_filters(products: list[dict]) -> list[dict]:
    """리뷰 < MIN_REVIEWS 또는 평점 < MIN_RATING 항목 제외."""
    result = []
    for p in products:
        rev = p.get("reviewCount") or 0
        try:
            rev = int(rev)
        except (TypeError, ValueError):
            rev = 0
        rating = p.get("rating") or p.get("productScore") or 0
        try:
            rating = float(rating)
        except (TypeError, ValueError):
            rating = 0.0
        # 리뷰 50 미만 또는 평점 4.5 미만이면 제외; 필드 없으면 포함
        if rev > 0 and rev < MIN_REVIEWS:
            continue
        if rating > 0 and rating < MIN_RATING:
            continue
        result.append(p)
    return result


def _normalize_product(item: dict) -> dict:
    """API 상품 항목을 백오피스 형식으로 정규화."""
    # 쿠팡 API 응답 구조는 다를 수 있음; 키는 필요 시 수정
    product_id = item.get("productId") or item.get("productId", "")
    name = item.get("productName") or item.get("productName") or ""
    price = item.get("productPrice") or item.get("salePrice") or item.get("price") or 0
    url = item.get("productUrl") or item.get("link") or ""
    image = item.get("productImage") or item.get("imageUrl") or item.get("thumbnail") or ""
    is_rocket = item.get("isRocket")
    category = item.get("categoryName") or item.get("category") or ""
    return {
        "productId": product_id,
        "productName": name,
        "price": price,
        "productUrl": url,
        "imageUrl": image,
        "isRocket": is_rocket,
        "category": category,
    }


def _extract_product_items(data: dict[str, Any]) -> list[dict]:
    """쿠팡 응답 payload에서 상품 배열을 추출."""
    items = data.get("data", {}).get("productData") or data.get("productData") or data.get("data") or []
    if isinstance(items, dict):
        items = list(items.values()) if items else []
    if not isinstance(items, list):
        return []
    return items


def _clean_keyword_text(text: str) -> str:
    """경량 키워드 정규화: 공백/특수문자 정리."""
    if not text:
        return ""
    t = str(text).strip()
    t = re.sub(r"\[[^\]]*\]|\([^\)]*\)", " ", t)
    t = re.sub(r"[/|]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _extract_keyword_from_product(item: dict[str, Any]) -> str:
    """상품명/카테고리에서 UI 시드 보강용 직관 키워드 1개를 추출."""
    name = _clean_keyword_text(str(item.get("productName") or ""))
    category = _clean_keyword_text(str(item.get("categoryName") or item.get("category") or ""))
    if name:
        primary = name.split(",")[0].strip()
        primary = primary.split(" - ")[0].strip()
        if primary:
            return primary
    return category


async def expand_keywords_from_coupang(
    seed_keywords: list[str],
    access_key: str,
    secret_key: str,
    *,
    max_keywords: int = 3,
    per_keyword_items: int = 10,
    timeout_seconds: float = 5.0,
) -> list[str]:
    """네이버 시드 보강용 경량 쿠팡 확장 키워드 수집."""
    if not seed_keywords or not access_key or not secret_key:
        return []

    path = "/v2/providers/affiliate_open_api/apis/openapi/products/search"
    queries = [kw.strip() for kw in seed_keywords if kw and kw.strip()][:max(1, max_keywords)]
    if not queries:
        return []

    out: list[str] = []
    seen: set[str] = set()
    async with httpx.AsyncClient() as client:
        for kw in queries:
            encoded_keyword = quote(kw)
            query = f"keyword={encoded_keyword}"
            url = f"https://api-gateway.coupang.com{path}?{query}"
            auth_header = build_authorization_header(access_key, secret_key, path, query)
            try:
                resp = await client.get(
                    url,
                    headers={"Authorization": auth_header},
                    timeout=timeout_seconds,
                )
                data = resp.json()
            except Exception:
                continue
            if data.get("rCode") and str(data.get("rCode")) != "0":
                continue

            items = _extract_product_items(data)[: max(1, per_keyword_items)]
            for item in items:
                candidate = _extract_keyword_from_product(item)
                key = candidate.lower()
                if not candidate or key in seen:
                    continue
                seen.add(key)
                out.append(candidate)
    return out


@dataclass(frozen=True)
class SearchProductsResult:
    """쿠팡 상품 검색 결과(정규화 상품 + 수집·필터 메타)."""

    products: list[dict]
    raw_collected: int
    filtered_count: int
    stop_reason: str
    queries_run: int


async def search_products(
    keyword: str,
    access_key: str,
    secret_key: str,
    limit: int = 10,
) -> SearchProductsResult:
    """쿠팡 상품 검색 후 필터 적용(리뷰>=50, 평점>=4.5). httpx 비동기 사용."""
    encoded_keyword = quote(keyword)

    path = "/v2/providers/affiliate_open_api/apis/openapi/products/search"
    request_limit = max(1, min(int(limit or 10), 50))
    # 운영 로그 기준으로 limit/page 조합이 지속적으로 "limit is out of range"를 반환하므로
    # 단일 keyword 호출만 사용해 API 호환성을 우선 보장한다.
    queries = [f"keyword={encoded_keyword}"]

    seen_ids: set[str] = set()
    merged_items: list[dict] = []
    queries_run = 0
    stop_reason = "exhausted_queries"

    async with httpx.AsyncClient() as client:
        for query in queries:
            url = f"https://api-gateway.coupang.com{path}?{query}"
            auth_header = build_authorization_header(access_key, secret_key, path, query)
            queries_run += 1
            try:
                resp = await client.get(
                    url,
                    headers={"Authorization": auth_header},
                    timeout=30.0,
                )
                data = resp.json()
            except Exception as e:
                print(f"쿠팡 검색 요청 실패(query={query}): {e}")
                continue

            if data.get("rCode") and str(data.get("rCode")) != "0":
                print(f"쿠팡 오류(query={query}): {data}")
                continue

            items = _extract_product_items(data)
            if not items:
                if "&page=" in query:
                    stop_reason = "empty_page"
                    break
                continue

            before_count = len(merged_items)
            for item in items:
                product_id = str(item.get("productId") or "").strip()
                dedupe_key = product_id or str(item.get("productUrl") or "").strip()
                if not dedupe_key or dedupe_key in seen_ids:
                    continue
                seen_ids.add(dedupe_key)
                merged_items.append(item)

            # 페이지를 바꿨는데 신규 데이터가 더 안 붙으면 조기 종료
            if len(merged_items) == before_count and "&page=" in query:
                stop_reason = "no_new_items_on_page"
                break

            filtered_count = len(_apply_filters(merged_items))
            if filtered_count >= request_limit:
                stop_reason = "target_met"
                break

    filtered = _apply_filters(merged_items)
    filtered_total = len(filtered)
    final_products = [_normalize_product(p) for p in filtered[:request_limit]]

    logger.debug(
        "coupang search_products keyword=%r stop=%s raw=%s filtered=%s returned=%s queries=%s",
        keyword,
        stop_reason,
        len(merged_items),
        filtered_total,
        len(final_products),
        queries_run,
    )

    return SearchProductsResult(
        products=final_products,
        raw_collected=len(merged_items),
        filtered_count=filtered_total,
        stop_reason=stop_reason,
        queries_run=queries_run,
    )


COUPANG_DEEPLINK_API_SUB_ID = "shortcrew"


async def generate_deeplinks(
    urls: list[str],
    access_key: str,
    secret_key: str,
) -> dict[str, str]:
    """쿠팡 딥링크 API로 URL 목록을 단축 URL로 변환. originalUrl -> shortenUrl 매핑 반환.

    API 본문 `subId`는 파트너스 정책에 맞춰 고정값(`COUPANG_DEEPLINK_API_SUB_ID`)만 사용한다.
    """
    if not urls:
        return {}

    # 🚨 [수정 포인트] URL 세척 제거! 쿠팡 API에 원본 그대로 보내야 안전합니다.
    path = "/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink"
    query = ""
    auth_header = build_authorization_header(
        access_key, secret_key, path, query, method="POST"
    )
    url = f"https://api-gateway.coupang.com{path}"

    body: dict[str, Any] = {
        "coupangUrls": urls,
        "subId": COUPANG_DEEPLINK_API_SUB_ID,
    }

    logger.info(
        "generate_deeplinks_request total_urls=%s url_kinds=%s url_samples=%s sub_id=%s",
        len(urls),
        _count_url_kinds(urls),
        [u[:200] for u in urls[:3]],
        COUPANG_DEEPLINK_API_SUB_ID,
    )

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            json=body,
            headers={
                "Authorization": auth_header,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        try:
            data = resp.json()
        except Exception:
            data = {}

    if resp.status_code >= 400:
        raise RuntimeError(
            f"deeplink_api_http_error status={resp.status_code} body={data}"
        )

    # 🚨 [수정 포인트] 쿠팡이 rCode를 숫자 0으로 줄 때를 대비해 str()로 완벽 방어
    if str(data.get("rCode")) != "0":
        raise RuntimeError(f"deeplink_api_business_error payload={data}")

    result: dict[str, str] = {}
    for item in data.get("data") or []:
        if isinstance(item, dict):
            orig = item.get("originalUrl")
            short = item.get("shortenUrl", "")
            if orig is not None:
                result[orig] = short

    short_values = [str(v or "").strip() for v in result.values()]
    logger.info(
        "generate_deeplinks_response status_code=%s mapped=%s mapped_kinds=%s samples=%s",
        resp.status_code,
        len(result),
        _count_url_kinds(short_values),
        [
            {"originalUrl": str(k)[:180], "shortenUrl": str(v)[:180]}
            for k, v in list(result.items())[:3]
        ],
    )

    # 성공 시 몇 개가 변환되었는지 터미널에 보고
    print(f"\n✅ [딥링크 변환 성공] {len(result)}개 링크 생성 완료!\n")
    return result
