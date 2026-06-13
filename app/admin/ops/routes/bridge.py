"""쇼츠-커머스 브리지 큐레이션 오케스트레이션.

홈캠카오스(지식쇼츠) 영상 주제를 씨앗으로, 채널 성격에 맞는 쿠팡 상품을 큐레이션해
인플루언서 몰(안지아픽 /safety)에 등록한다. 06.운영가이드/09_쇼츠커머스브리지설계.md.

흐름(전부 코드, n8n 은 스케줄/트리거만):
  1) 후보풀 = 쿠팡 검색(채널 보안 키워드)  ← niche 채널은 베스트/골드박스보다 검색 풀이 연관성↑
  2) 주제별 선정 = Gemini(주제 + 페르소나, 무관하면 제외)
  3) 딥링크(subId=shortcrew) → 몰 Product 등록(influencer_slug=safety)

인증은 어드민 쿠키가 아니라 OPS_API_TOKEN(헤더 X-Ops-Token) — n8n 호출용.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.deps import get_db
from app.admin.ops.channels import get_channels
from app.admin.ops.routes.instagram_publish import require_ops_token
from app.admin.ops.services import coupang, gemini_curator
from app.admin.ops.services.gemini_review_draft import generate_review_draft
from models import Influencer, Review

router = APIRouter()

# 쿼터·프롬프트 보호 상한.
_MAX_KEYWORDS = 8
_MAX_POOL = 40


def _coupang_keys() -> tuple[str, str]:
    return (
        (os.environ.get("COUPANG_ACCESS_KEY") or "").strip(),
        (os.environ.get("COUPANG_SECRET_KEY") or "").strip(),
    )


def _gemini_key() -> str:
    return (os.environ.get("GOOGLE_GEMINI_KEY") or "").strip()


def _find_channel(channel_id: str) -> dict | None:
    cid = (channel_id or "").strip()
    for ch in get_channels():
        if (ch.get("channel_id") or "").strip() == cid:
            return ch
    return None


class CurateBody(BaseModel):
    channel_id: str = "105"
    topics: list[str] = []          # 영상 주제(씨앗). 비우면 후보풀만 미리보기.
    search_keywords: list[str] = []  # 후보풀 검색어. 비우면 채널 trend_keywords 사용.
    persona: str = ""               # Gemini 선정 페르소나. 비우면 채널명 기반.
    search_limit: int = 20          # 키워드당 검색 상한.
    dry_run: bool = True            # true 면 적재 없이 미리보기.
    auto_blog: bool = False         # true 면 적재된 상품마다 블로그(Review) 자동 생성·발행(dry_run 시 무시).


def _curate_result(body, slug, pool, pool_meta, persona, picks, *, written, blogs) -> dict:
    return {
        "channel_id": body.channel_id,
        "mall_slug": slug,
        "mode": "curate",
        "dry_run": body.dry_run,
        "auto_blog": body.auto_blog,
        "pool_size": len(pool),
        "pool_meta": pool_meta,
        "persona": persona,
        "picks": [
            {
                "topic": pk["topic"],
                "picked": (pk["product"] or {}).get("productName"),
                "price": (pk["product"] or {}).get("price"),
                "reason": pk.get("reason"),
                "deeplink": pk.get("deeplink"),
                "sheet": pk.get("sheet"),
                "blog": pk.get("blog"),
            }
            for pk in picks
        ],
        "written_to_sheet": written,
        "blogs_created": blogs,
    }


def _clean_product_url(p: dict) -> str:
    """딥링크 입력용 클린 상품 URL(`vp/products/{id}`).

    쿠팡 검색 결과 URL은 이미 lptag·src 등 제휴태그가 붙어 있어, 그대로 딥링크하면
    MIXED 토큰이 되며 subId(shortcrew)가 랜딩 URL에서 유실된다. 클린 URL로 넣어야
    subId 가 정상 전파된다(검증 완료).
    """
    pid = str(p.get("productId") or "").strip()
    if pid:
        return f"https://www.coupang.com/vp/products/{pid}"
    return str(p.get("productUrl") or "").strip()


def _dedupe_pool(products: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for p in products:
        key = str(p.get("productId") or "").strip() or str(p.get("productUrl") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


@router.post("/curate")
async def curate_products(
    body: CurateBody,
    db: Session = Depends(get_db),
    _: None = Depends(require_ops_token),
):
    """채널 성격에 맞는 쿠팡 상품을 주제별로 큐레이션 → (옵션) 몰에 등록."""
    ch = _find_channel(body.channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail=f"channel {body.channel_id} not found")

    access_key, secret_key = _coupang_keys()
    if not access_key or not secret_key:
        raise HTTPException(status_code=503, detail="COUPANG_ACCESS_KEY/SECRET_KEY 미설정")
    gem_key = _gemini_key()

    slug = (ch.get("mall_influencer_slug") or "").strip()
    if not slug:
        raise HTTPException(status_code=400, detail=f"channel {body.channel_id} has no mall_influencer_slug")
    persona = body.persona.strip() or f"{ch.get('name') or slug} 보안 상품 큐레이터"

    keywords = [k.strip() for k in (body.search_keywords or ch.get("trend_keywords") or []) if k.strip()]
    keywords = keywords[:_MAX_KEYWORDS]
    if not keywords:
        raise HTTPException(status_code=400, detail="검색 키워드가 없습니다(search_keywords 또는 채널 trend_keywords).")

    # 1) 후보풀 = 보안 키워드 검색
    pool: list[dict] = []
    pool_meta: list[dict] = []
    for kw in keywords:
        res = await coupang.search_products(kw, access_key, secret_key, limit=body.search_limit)
        pool.extend(res.products)
        pool_meta.append({"keyword": kw, "found": len(res.products), "stop_reason": res.stop_reason})
    pool = _dedupe_pool(pool)[:_MAX_POOL]

    # 주제가 없으면 후보풀만 미리보기(선정·적재 없음)
    if not body.topics:
        return {
            "channel_id": body.channel_id,
            "mode": "pool_preview",
            "pool_size": len(pool),
            "pool_meta": pool_meta,
            "pool": [{"productName": p.get("productName"), "price": p.get("price")} for p in pool[:20]],
        }

    if not gem_key:
        raise HTTPException(status_code=503, detail="GOOGLE_GEMINI_KEY 미설정(주제 선정 불가)")
    if not pool:
        return {"channel_id": body.channel_id, "mode": "curate", "pool_size": 0,
                "picks": [], "persisted": 0, "note": "후보풀이 비어 있습니다."}

    # 2) 주제별 Gemini 선정
    picks: list[dict] = []
    for topic in [t.strip() for t in body.topics if t.strip()]:
        sel = await gemini_curator.pick_product_for_topic(
            gem_key, topic=topic, candidates=pool, persona=persona,
        )
        if sel.get("relevant") and sel.get("picked"):
            picks.append({"topic": topic, "product": sel["picked"], "reason": sel.get("selection_reason", "")})
        else:
            picks.append({"topic": topic, "product": None, "reason": sel.get("selection_reason", "연관 상품 없음")})

    # 선정된 상품 → 클린 URL(vp/products/{id})로 딥링크 (이미-제휴 URL 넣으면 subId 유실)
    chosen = [pk for pk in picks if pk["product"]]
    for pk in chosen:
        pk["clean_url"] = _clean_product_url(pk["product"])
    urls = [pk["clean_url"] for pk in chosen if pk["clean_url"]]
    deeplinks: dict[str, str] = {}
    if urls:
        try:
            deeplinks = await coupang.generate_deeplinks(urls, access_key, secret_key)
        except Exception as e:  # 딥링크 실패해도 클린 URL로 진행
            deeplinks = {}
            for pk in chosen:
                pk["deeplink_error"] = str(e)[:120]

    # 최종 구매 URL = 딥링크(우선) / 실패 시 클린 URL
    for pk in chosen:
        cu = pk["clean_url"]
        pk["deeplink"] = deeplinks.get(cu, "") or cu

    # dry_run: 시트·DB 미기록, 미리보기만
    if body.dry_run:
        return _curate_result(body, slug, pool, pool_meta, persona, picks, written=0, blogs=0)

    # 3) 상품 → 채널 시트(탭3) 적재. 상품의 단일 소스는 '시트'(DB 아님).
    sheet_id = (ch.get("google_sheet_id") or "").strip()
    tab_name = (ch.get("sheet_tab_name") or "상품목록").strip()
    if not sheet_id:
        raise HTTPException(
            status_code=503,
            detail=(
                f"채널 {body.channel_id} 상품 시트 미설정(CHANNEL_{body.channel_id}_FILE_ID/TAB). "
                "홈캠카오스 스프레드시트의 안지아(탭3)를 연결하세요."
            ),
        )

    from app.admin.ops.services.google_sheets import append_rows, build_rows, get_existing_values

    existing = await get_existing_values(sheet_id, tab_name, column="F")  # F열=쿠팡URL 중복 방지

    want_blog = body.auto_blog and bool(gem_key)
    inf_display = slug
    if want_blog:
        inf = db.scalar(select(Influencer).where(Influencer.name_slug == slug))
        inf_display = inf.display_name if inf else slug

    sheet_rows: list[dict] = []
    blogs_created = 0
    for pk in chosen:
        p = pk["product"]
        clean = pk["clean_url"]  # F열=클린 상품URL(안정적 → 중복제거 정확)
        deep = pk["deeplink"]
        if not clean or clean in existing:
            pk["sheet"] = "dup_skip"
            continue
        sheet_rows.append({
            "category": p.get("category") or "",
            "productName": p.get("productName") or "",
            "price": p.get("price") or 0,
            "imageUrl": p.get("imageUrl") or "",
            "productUrl": clean,
            "deepLink": deep,
            # 블로그 자동발행과 동시에 즉시 노출(게시중). 블로그 없이 적재면 대기.
            "status": "게시중" if want_blog else "대기",
        })
        pk["sheet"] = "ok"

        # 블로그(Review) → DB. 시트상품을 sheet_product_* 로 1:1 연결(DB Product 미생성).
        if want_blog:
            try:
                price = float(p.get("price") or 0)
            except (TypeError, ValueError):
                price = 0.0
            try:
                draft = await generate_review_draft(
                    gem_key,
                    influencer_display=inf_display,
                    influencer_slug=slug,
                    product_title=str(p.get("productName") or ""),
                    product_price=price,
                    product_url=deep or clean,
                    image_url=str(p.get("imageUrl") or ""),
                    extra_instruction=(
                        f"이 글은 '{pk['topic']}' 주제의 쇼츠와 연결됩니다. "
                        "해당 주제 맥락(보안 상황)을 도입부에 자연스럽게 녹이세요."
                    ),
                )
                rev = Review(
                    influencer_slug=slug,
                    title=(draft.get("title") or str(p.get("productName") or ""))[:255],
                    content=draft.get("html") or "",
                    sheet_product_title=str(p.get("productName") or "")[:255],
                    sheet_product_deeplink=(deep or clean)[:500],
                )
                db.add(rev)
                blogs_created += 1
                pk["blog"] = "ok"
            except Exception as e:  # 블로그 실패해도 시트 적재는 유지
                pk["blog"] = f"error: {str(e)[:80]}"

    written = len(sheet_rows)
    if sheet_rows:
        rows = build_rows(sheet_rows, channel_id=body.channel_id)
        await append_rows(sheet_id, tab_name, rows)
    if blogs_created:
        db.commit()

    return _curate_result(body, slug, pool, pool_meta, persona, picks, written=written, blogs=blogs_created)
