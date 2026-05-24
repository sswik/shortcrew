"""네이버 데이터랩 쇼핑인사이트 API: 카테고리 키워드 트렌드, ratio 기준 상위 20개 반환."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import httpx

NAVER_DATALAB_BASE = "https://openapi.naver.com"
CATEGORY_KEYWORDS_PATH = "/v1/datalab/shopping/category/keywords"
DEFAULT_TARGET_COUNT = 20
_GENERIC_STOPWORDS = {
    "무소음", "대용량", "고급형", "프리미엄", "신상", "인기", "추천", "정품", "국내산",
}


async def fetch_trend_keywords(
    client_id: str,
    client_secret: str,
    category_id: str,
    keywords: list[str],
    days_back: int = 7,
) -> list[dict]:
    """네이버 데이터랩 category/keywords 호출 후 ratio 내림차순 정렬. 최대 20개 반환."""
    if not client_id or not client_secret:
        return []
    if not keywords:
        return []

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days_back)
    start_str = start.isoformat()
    end_str = end.isoformat()

    # API는 요청당 최대 5개 키워드; 5개씩 잘라서 끝까지(최대 50개) 요청 후 결과 병합
    all_out = []
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
        "Content-Type": "application/json",
    }
    for start_idx in range(0, min(50, len(keywords)), 5):
        batch = keywords[start_idx : start_idx + 5]
        keyword_groups = [{"name": kw, "param": [kw]} for kw in batch]
        if not keyword_groups:
            continue
        body = {
            "startDate": start_str,
            "endDate": end_str,
            "timeUnit": "date",
            "category": category_id,
            "keyword": keyword_groups,
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    NAVER_DATALAB_BASE + CATEGORY_KEYWORDS_PATH,
                    json=body,
                    headers=headers,
                    timeout=15.0,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            print(f"네이버 호출 중 오류 발생: {e}")
            continue  # 에러 나면 다음 배치로 넘어가기

        results = data.get("results") or []
        for r in results:
            kw = (r.get("keyword") or [None])[0] or r.get("title") or ""
            arr = r.get("data") or []
            ratio = 0.0
            if arr:
                ratio = float(arr[-1].get("ratio") or 0)
            all_out.append({"keyword": kw, "ratio": ratio})

    all_out.sort(key=lambda x: -x["ratio"])
    top20 = all_out[:20]
    for i, item in enumerate(top20, 1):
        item["rank"] = i
    return top20


async def get_naver_trending_keywords(
    client_id: str,
    client_secret: str,
    category_ids: list[str],
    keywords: list[str],
    days_back: int = 7,
) -> list[dict]:
    """여러 카테고리 ID에 대해 각각 API 호출 후 결과 병합·중복 제거·ratio 기준 상위 20개 반환."""
    if not category_ids:
        return []
    if not keywords:
        return []

    merged: list[dict] = []
    for category_id in category_ids:
        part = await fetch_trend_keywords(
            client_id, client_secret, category_id.strip(), keywords, days_back
        )
        merged.extend(part)

    # 중복 키워드: ratio가 큰 값 하나만 유지
    by_keyword: dict[str, float] = {}
    for item in merged:
        kw = (item.get("keyword") or "").strip()
        if not kw:
            continue
        ratio = float(item.get("ratio") or 0)
        if kw not in by_keyword or ratio > by_keyword[kw]:
            by_keyword[kw] = ratio

    # ratio 내림차순 정렬 후 상위 20개, rank 부여
    sorted_items = sorted(by_keyword.items(), key=lambda x: -x[1])[:20]
    result = [
        {"keyword": kw, "ratio": ratio, "rank": i}
        for i, (kw, ratio) in enumerate(sorted_items, 1)
    ]
    return result


async def _fetch_monitoring_keywords(
    client_id: str,
    client_secret: str,
    category_ids: list[str],
    monitor_keywords: list[str],
    days_back: int = 7,
) -> list[dict]:
    """monitor_keywords에 대해 category/keywords 호출 후 ratio 수집, 중복 시 max ratio, ratio 내림차순."""
    if not monitor_keywords:
        return []
    merged: list[dict] = []
    for category_id in category_ids:
        try:
            part = await fetch_trend_keywords(
                client_id, client_secret, category_id.strip(), monitor_keywords, days_back
            )
            merged.extend(part)
        except Exception as e:
            print(f"모니터링 카테고리 {category_id} 오류: {e}")
            continue
    by_keyword: dict[str, float] = {}
    for item in merged:
        kw = (item.get("keyword") or "").strip()
        if not kw:
            continue
        ratio = float(item.get("ratio") or 0)
        if kw not in by_keyword or ratio > by_keyword[kw]:
            by_keyword[kw] = ratio
    sorted_items = sorted(by_keyword.items(), key=lambda x: -x[1])
    return [
        {"keyword": kw, "ratio": ratio, "rank": i}
        for i, (kw, ratio) in enumerate(sorted_items, 1)
    ]


def _normalize_seed_keyword(keyword: str) -> str:
    kw = (keyword or "").strip().replace("#", "")
    kw = " ".join(kw.split())
    return kw


def _is_valid_seed_keyword(keyword: str) -> bool:
    kw = _normalize_seed_keyword(keyword)
    if not kw:
        return False
    if len(kw) < 2 or len(kw) > 40:
        return False
    if kw in _GENERIC_STOPWORDS:
        return False
    return True


def _merge_unique_keywords(keywords: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in keywords:
        kw = _normalize_seed_keyword(raw)
        if not _is_valid_seed_keyword(kw):
            continue
        key = kw.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(kw)
    return out


def _rank_items_with_source(
    ranked_items: list[dict],
    source: str,
) -> list[dict]:
    out: list[dict] = []
    for item in ranked_items:
        kw = _normalize_seed_keyword(str(item.get("keyword") or ""))
        if not _is_valid_seed_keyword(kw):
            continue
        out.append(
            {
                "keyword": kw,
                "ratio": float(item.get("ratio") or 0),
                "source": source,
            }
        )
    return out


async def build_dynamic_seed_keywords(
    client_id: str,
    client_secret: str,
    category_ids: list[str],
    trend_keywords: list[str],
    monitor_keywords: list[str],
    coupang_access_key: str = "",
    coupang_secret_key: str = "",
    target_count: int = DEFAULT_TARGET_COUNT,
) -> tuple[list[dict], dict]:
    """UI 노출용 시드 20개를 동적으로 생성하고 메타를 반환."""
    target_count = max(1, int(target_count or DEFAULT_TARGET_COUNT))
    naver_seed_candidates = _merge_unique_keywords((trend_keywords or []) + (monitor_keywords or []))

    # 1) 네이버 우선: 기존 시드(트렌드+모니터링)를 점수화
    scored_from_naver = await get_naver_trending_keywords(
        client_id, client_secret, category_ids, naver_seed_candidates, days_back=7
    )
    merged_ranked = _rank_items_with_source(scored_from_naver, "naver")
    merged_keywords = [x["keyword"] for x in merged_ranked]

    # 2) 부족할 때만 경량 쿠팡 확장
    if len(merged_keywords) < target_count and coupang_access_key and coupang_secret_key:
        try:
            from app.admin.ops.services.coupang import expand_keywords_from_coupang

            expansion_seed = merged_keywords[:5] or naver_seed_candidates[:5]
            coupang_expanded = await expand_keywords_from_coupang(
                expansion_seed,
                coupang_access_key,
                coupang_secret_key,
                max_keywords=3,
                per_keyword_items=10,
                timeout_seconds=5.0,
            )
            combined_candidates = _merge_unique_keywords(naver_seed_candidates + coupang_expanded)
            rescored = await get_naver_trending_keywords(
                client_id, client_secret, category_ids, combined_candidates, days_back=7
            )
            merged_ranked = _rank_items_with_source(rescored, "naver")
            coupang_set = {kw.lower() for kw in _merge_unique_keywords(coupang_expanded)}
            for item in merged_ranked:
                if item["keyword"].lower() in coupang_set:
                    item["source"] = "coupang"
        except Exception:
            pass

    # 3) fallback: 그래도 부족하면 최소 기본 키워드로 보강
    if len(merged_ranked) < target_count:
        try:
            from app.admin.ops.channels import DEFAULT_TREND_KEYWORDS

            fallback_candidates = _merge_unique_keywords(DEFAULT_TREND_KEYWORDS)
        except Exception:
            fallback_candidates = []
        fallback_existing = {item["keyword"].lower() for item in merged_ranked}
        for kw in fallback_candidates:
            if kw.lower() in fallback_existing:
                continue
            merged_ranked.append({"keyword": kw, "ratio": 0.0, "source": "fallback"})
            fallback_existing.add(kw.lower())
            if len(merged_ranked) >= target_count:
                break

    final = merged_ranked[:target_count]
    source_counts = {"naver": 0, "coupang": 0, "fallback": 0}
    seed_keywords: list[dict] = []
    for i, item in enumerate(final, 1):
        src = str(item.get("source") or "naver")
        if src not in source_counts:
            src = "naver"
        source_counts[src] += 1
        seed_keywords.append(
            {
                "keyword": item["keyword"],
                "ratio": float(item.get("ratio") or 0),
                "rank": i,
                "source": src,
            }
        )
    meta = {
        "target_count": target_count,
        "final_count": len(seed_keywords),
        "source_counts": source_counts,
    }
    return seed_keywords, meta


async def get_naver_trend_two_track(
    client_id: str,
    client_secret: str,
    category_ids: list[str],
    trend_keywords: list[str],
    monitor_keywords: list[str],
    coupang_access_key: str = "",
    coupang_secret_key: str = "",
    target_count: int = DEFAULT_TARGET_COUNT,
    days_back: int = 7,
) -> dict:
    """실시간 발굴(discovery) + 관심사 모니터링(monitoring) 두 트랙. { discovery, monitoring } 반환. 트랙별 실패 시 해당 트랙만 []."""
    discovery: list[dict] = []
    monitoring: list[dict] = []
    seed_meta = {
        "target_count": target_count,
        "final_count": 0,
        "source_counts": {"naver": 0, "coupang": 0, "fallback": 0},
    }
    try:
        discovery, seed_meta = await build_dynamic_seed_keywords(
            client_id,
            client_secret,
            category_ids,
            trend_keywords,
            monitor_keywords,
            coupang_access_key,
            coupang_secret_key,
            target_count=target_count,
        )
    except Exception as e:
        print(f"Discovery 트랙 오류: {e}")
    try:
        monitoring = await _fetch_monitoring_keywords(
            client_id, client_secret, category_ids, monitor_keywords, days_back
        )
    except Exception as e:
        print(f"Monitoring 트랙 오류: {e}")
    return {
        "discovery": discovery,
        "monitoring": monitoring,
        "seed_keywords": discovery,
        "seed_meta": seed_meta,
    }
