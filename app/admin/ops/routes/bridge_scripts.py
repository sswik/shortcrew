"""쇼츠-커머스 브리지 · 후기→대본 배선 (파일럿: 골프02·테니스03).

큐레이션이 채운 상품탭(오세련픽-상품/왕세림픽-상품)에서 상품을 읽어,
인플루언서가 남긴 실제 후기(reviews.content)가 있으면 1인칭 사용후기 대본을,
없으면 상품군 추천형(폴백) 대본을 생성해 AFxx가 읽는 `시트1`에 적재한다.

흐름(전부 코드, n8n 은 주간 스케줄/트리거만):
  1) 상품탭에서 게시중 상품 N개(기본 7) 로드
  2) 상품명 ↔ reviews 매칭 → 있으면 후기형, 없으면 폴백형 대본(Gemini)
  3) 시트1(A~X)에 상태=제작대기 + 예약시간(요일당 1편)으로 append → AFxx 자동 발행

인증은 OPS_API_TOKEN(헤더 X-Ops-Token) — n8n 호출용. dry_run 기본 true.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.deps import get_db
from app.admin.ops.channels import get_channels
from app.admin.ops.routes.instagram_publish import require_ops_token
from app.admin.ops.services import gemini_shorts_script
from app.admin.ops.services.google_sheets import append_rows, get_all_rows
from app.admin.ops.services.shorts_name_normalize import names_equivalent
from models import Pump, Review

router = APIRouter()

# 시트1 24컬럼(A~X) — AFxx 발행 파이프라인 스키마와 1:1.
_SHEET1_TAB = "시트1"
_SHEET1_RANGE = "A:X"
# 상품탭(A:K) 컬럼 인덱스 (build_rows 스펙과 동일)
_P_CATEGORY, _P_NAME, _P_PRICE, _P_IMAGE, _P_COUPANG, _P_DEEPLINK, _P_STATUS = 1, 2, 3, 4, 5, 6, 8


def _gemini_key() -> str:
    return (os.environ.get("GOOGLE_GEMINI_KEY") or "").strip()


def _find_channel(channel_id: str) -> dict | None:
    cid = (channel_id or "").strip()
    for ch in get_channels():
        if (ch.get("channel_id") or "").strip() == cid:
            return ch
    return None


def _cell(row: list, idx: int) -> str:
    return str(row[idx]).strip() if idx < len(row) and row[idx] is not None else ""


class ScriptBody(BaseModel):
    channel_id: str = "02"           # 파일럿: 02(골프)/03(테니스)
    count: int = 7                   # 이번 주 대본 편수(요일당 1편 = 7)
    dry_run: bool = True             # true 면 시트 미적재, 미리보기만
    start_hour: int = 7              # 예약시간 시(HH). AFxx 발행(11~12시)보다 일러야 같은 날 픽업.
    start_offset_days: int = 1       # 첫 편 예약 = 오늘+N일(기본 내일부터)


def _match_review(db: Session, slug: str, product_name: str) -> Review | None:
    """동일 인플루언서 후기 중 상품명과 정규화 일치하는 것(시트상품명 또는 DB상품명)."""
    reviews = db.scalars(
        select(Review).where(func.lower(Review.influencer_slug) == slug.lower())
        .order_by(Review.created_at.desc())
    ).all()
    for r in reviews:
        cand = (r.sheet_product_title or "").strip() or (r.product.title if r.product else "")
        if cand and names_equivalent(cand, product_name):
            return r
    return None


def _next_no(sheet1_rows: list[list]) -> int:
    """시트1 A열(No) 최대값+1. 헤더/수식/빈칸은 무시."""
    mx = 0
    for row in sheet1_rows[1:]:
        v = _cell(row, 0)
        if v.isdigit():
            mx = max(mx, int(v))
    return mx + 1


@router.post("/scripts")
async def build_review_scripts(
    body: ScriptBody,
    db: Session = Depends(get_db),
    _: None = Depends(require_ops_token),
):
    """상품탭 상품 → (후기형/폴백형) 대본 → 시트1 적재. 골프02·테니스03 파일럿."""
    ch = _find_channel(body.channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail=f"channel {body.channel_id} not found")

    gem_key = _gemini_key()
    if not gem_key:
        raise HTTPException(status_code=503, detail="GOOGLE_GEMINI_KEY 미설정(대본 생성 불가)")

    slug = (ch.get("mall_pump_slug") or "").strip()
    sheet_id = (ch.get("google_sheet_id") or "").strip()
    product_tab = (ch.get("sheet_tab_name") or "").strip()
    if not slug or not sheet_id or not product_tab:
        raise HTTPException(
            status_code=400,
            detail=f"channel {body.channel_id} 설정 미비(slug/FILE_ID/TAB).",
        )

    inf = db.scalar(select(Pump).where(Pump.name_slug == slug))
    inf_display = inf.display_name if inf else slug
    field_kr = (ch.get("name") or slug)

    # 1) 상품탭에서 게시중 상품 로드
    prod_rows = await get_all_rows(sheet_id, product_tab, "A:K")
    products: list[dict] = []
    for row in prod_rows[1:]:
        if _cell(row, _P_STATUS) != "게시중":
            continue
        name = _cell(row, _P_NAME)
        deeplink = _cell(row, _P_DEEPLINK) or _cell(row, _P_COUPANG)
        if not name or not deeplink:
            continue
        products.append({
            "category": _cell(row, _P_CATEGORY),
            "name": name,
            "price": _cell(row, _P_PRICE),
            "image": _cell(row, _P_IMAGE),
            "deeplink": deeplink,
        })

    # 2) 시트1 기존 상품(중복 방지: W열=coupang_url) + 다음 No
    sheet1_rows = await get_all_rows(sheet_id, _SHEET1_TAB, _SHEET1_RANGE)
    existing_links = {_cell(r, 22) for r in sheet1_rows[1:] if _cell(r, 22)}
    next_no = _next_no(sheet1_rows)

    picks = [p for p in products if p["deeplink"] not in existing_links][: max(1, body.count)]
    if not picks:
        return {"channel_id": body.channel_id, "mode": "scripts", "written": 0,
                "note": "적재할 신규 상품이 없습니다(모두 시트1에 존재하거나 상품탭 비어있음)."}

    # 3) 상품마다 대본 생성(후기형/폴백형) → 시트1 행
    out_rows: list[list] = []
    preview: list[dict] = []
    base = datetime.now().replace(hour=body.start_hour, minute=0, second=0, microsecond=0)
    for i, p in enumerate(picks):
        try:
            price = float(str(p["price"]).replace(",", "") or 0)
        except (TypeError, ValueError):
            price = 0.0
        rv = _match_review(db, slug, p["name"])
        used = "review" if rv else "fallback"
        s = await gemini_shorts_script.generate_shorts_script(
            gem_key,
            influencer_display=inf_display,
            field_kr=field_kr,
            product_title=p["name"],
            product_price=price,
            product_url=p["deeplink"],
            image_url=p["image"],
            category=p["category"],
            review_content=(rv.content if rv else ""),
        )
        no = next_no + i
        sched = (base + timedelta(days=body.start_offset_days + i)).strftime("%Y-%m-%d %H:%M:%S")
        desc = f"{s['description']}\n\n▶ 상품 보기: {p['deeplink']}"
        # A~X (24열): 출력 컬럼(P~X 등)은 파이프라인이 채우므로 공란
        out_rows.append([
            no,                       # A No
            "제작대기",                # B 상태 (발행 트리거 값)
            "Stage1 대기",            # C 다음단계(표시용)
            sched,                    # D 예약시간
            p["category"] or field_kr,  # E 카테고리
            s["topic"],               # F 주제
            s["title"],               # G 제목
            s["script"],              # H 대본
            s["video_length"],        # I 영상_길이
            desc,                     # J 설명(+딥링크)
            s["scene1_prompt"],       # K scene1
            s["scene2_prompt"],       # L scene2
            s["scene3_prompt"],       # M scene3
            s["scene4_prompt"],       # N scene4
            s["scene5_prompt"],       # O scene5
            "", "", "", "", "", "", "",  # P~V 출력 컬럼(공란)
            p["deeplink"],            # W coupang_url
            "",                       # X youtube_video_id
        ])
        preview.append({
            "no": no, "product": p["name"], "mode": used, "schedule": sched,
            "title": s["title"], "video_length": s["video_length"],
            "script": s["script"], "description": desc,
            "scenes": [s["scene1_prompt"], s["scene2_prompt"], s["scene3_prompt"],
                       s["scene4_prompt"], s["scene5_prompt"]],
        })

    written = 0
    if not body.dry_run and out_rows:
        await append_rows(sheet_id, _SHEET1_TAB, out_rows, column_range=_SHEET1_RANGE)
        written = len(out_rows)

    return {
        "channel_id": body.channel_id,
        "mall_slug": slug,
        "mode": "scripts",
        "dry_run": body.dry_run,
        "candidates": len(products),
        "written": written,
        "picks": preview,
        "review_based": sum(1 for x in preview if x["mode"] == "review"),
        "fallback": sum(1 for x in preview if x["mode"] == "fallback"),
    }
