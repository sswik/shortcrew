"""쇼츠 시트 트리거 리뷰: 시트 읽기 → 매칭 → 자막 → Gemini → DB."""

from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.ops.channels import get_channels
from app.admin.ops.services.coupang import generate_deeplinks, search_products
from app.admin.ops.services.gemini_review_from_sheet_shorts import (
    generate_review_from_sheet_transcript,
    pick_product_keyword_from_transcript,
)
from app.admin.ops.services.google_sheets import get_all_rows
from app.admin.ops.services.review_publish_service import (
    create_review_from_shorts_pipeline,
    find_product_for_sheet_product_name,
    resolve_influencer_slug_for_mall,
)
from app.admin.ops.services.shorts_product_autolink import (
    upsert_product_in_db,
    upsert_product_row_in_sheet,
)
from app.admin.ops.services.shorts_review_config import (
    ShortsReviewConfig,
    today_for_shorts_plan_sheet,
)
from app.admin.ops.services.shorts_sheet_matcher import (
    _looks_like_youtube_url,
    latest_matchable_plan_date,
    match_shorts_sheet_rows,
    parse_sheet_date_cell,
    youtube_video_id_from_url,
)
from app.admin.ops.services.youtube_shorts_transcript import resolve_transcript_text
from models import Influencer, Review


def _channel_for_id(channel_id: str) -> dict | None:
    cid = (channel_id or "").strip()
    for ch in get_channels():
        if (ch.get("channel_id") or "").strip() == cid:
            return ch
    return None


def _candidate_plan_rows(
    cfg: ShortsReviewConfig,
    plan_rows: list[list[str]],
    *,
    plan_day,
) -> list[dict]:
    out: list[dict] = []
    for row in plan_rows[1:]:
        st = str(row[cfg.plan_status_col]).strip() if cfg.plan_status_col < len(row) else ""
        if st != cfg.plan_status_value:
            continue
        d_raw = str(row[cfg.plan_date_col]).strip() if cfg.plan_date_col < len(row) else ""
        d = parse_sheet_date_cell(d_raw)
        if d != plan_day:
            continue
        yt = str(row[cfg.plan_youtube_col]).strip() if cfg.plan_youtube_col < len(row) else ""
        if not _looks_like_youtube_url(yt):
            continue
        vid = youtube_video_id_from_url(yt)
        if not vid:
            continue
        pname = str(row[cfg.plan_product_col]).strip() if cfg.plan_product_col < len(row) else ""
        if not pname:
            continue
        out.append(
            {
                "youtube_url": yt,
                "video_id": vid,
                "plan_product_name": pname,
            }
        )
    return out


def _latest_candidate_plan_day(cfg: ShortsReviewConfig, plan_rows: list[list[str]], *, not_after):
    latest = None
    for row in plan_rows[1:]:
        st = str(row[cfg.plan_status_col]).strip() if cfg.plan_status_col < len(row) else ""
        if st != cfg.plan_status_value:
            continue
        d_raw = str(row[cfg.plan_date_col]).strip() if cfg.plan_date_col < len(row) else ""
        d = parse_sheet_date_cell(d_raw)
        if d is None or d > not_after:
            continue
        yt = str(row[cfg.plan_youtube_col]).strip() if cfg.plan_youtube_col < len(row) else ""
        if not _looks_like_youtube_url(yt):
            continue
        vid = youtube_video_id_from_url(yt)
        if not vid:
            continue
        pname = str(row[cfg.plan_product_col]).strip() if cfg.plan_product_col < len(row) else ""
        if not pname:
            continue
        if latest is None or d > latest:
            latest = d
    return latest


async def run_shorts_review_pipeline_for_channel(
    db: Session,
    cfg: ShortsReviewConfig,
    *,
    gemini_api_key: str,
    youtube_api_key: str,
    dry_run: bool = False,
    limit: int | None = None,
) -> list[str]:
    """한 채널 처리. 사람이 읽기 쉬운 로그 문자열 목록 반환."""
    log: list[str] = []
    infl = resolve_influencer_slug_for_mall(db, cfg.mall_influencer_slug)
    if not infl:
        log.append(f"[{cfg.channel_id}] mall_influencer_slug 에 맞는 influencers.name_slug 없음 — 스킵")
        return log

    try:
        plan_rows = await get_all_rows(cfg.spreadsheet_id, cfg.plan_tab, cfg.plan_range)
        product_rows = await get_all_rows(cfg.spreadsheet_id, cfg.product_tab, cfg.product_range)
    except Exception as e:
        log.append(f"[{cfg.channel_id}] 시트 읽기 실패: {e}")
        return log

    plan_day = today_for_shorts_plan_sheet(cfg)
    log.append(f"[{cfg.channel_id}] 플랜 기준일({cfg.plan_date_tz}): {plan_day}")
    matches = match_shorts_sheet_rows(cfg, plan_rows, product_rows, plan_day)
    log.append(f"[{cfg.channel_id}] 매칭 행 수(제한 전): {len(matches)}")
    candidates = _candidate_plan_rows(cfg, plan_rows, plan_day=plan_day)
    log.append(f"[{cfg.channel_id}] 기획 후보 행 수(날짜/상태/유튜브 기준): {len(candidates)}")
    if len(matches) == 0:
        fallback_day = latest_matchable_plan_date(
            cfg,
            plan_rows,
            product_rows,
            not_after=plan_day,
        )
        if fallback_day is not None and fallback_day != plan_day:
            matches = match_shorts_sheet_rows(cfg, plan_rows, product_rows, fallback_day)
            log.append(
                f"[{cfg.channel_id}] 오늘 매칭 없음 → 최신 매칭 가능일({fallback_day}) fallback: {len(matches)}건"
            )
            candidates = _candidate_plan_rows(cfg, plan_rows, plan_day=fallback_day)
            log.append(
                f"[{cfg.channel_id}] fallback 기준 기획 후보 행 수: {len(candidates)}"
            )
        elif not candidates:
            candidate_day = _latest_candidate_plan_day(cfg, plan_rows, not_after=plan_day)
            if candidate_day is not None and candidate_day != plan_day:
                candidates = _candidate_plan_rows(cfg, plan_rows, plan_day=candidate_day)
                log.append(
                    f"[{cfg.channel_id}] 오늘 후보 없음 → 최신 후보일({candidate_day}) fallback: {len(candidates)}건"
                )

    if limit is not None and limit > 0:
        matches = matches[:limit]
        log.append(f"[{cfg.channel_id}] --limit 적용 후 처리 대상: {len(matches)}건")
        candidates = candidates[:limit]
    if dry_run:
        log.append(f"[{cfg.channel_id}] ** dry-run: DB INSERT 없음 **")

    display_name = infl
    inf_row = db.scalar(select(Influencer).where(Influencer.name_slug == infl))
    if inf_row and (inf_row.display_name or "").strip():
        display_name = inf_row.display_name.strip()

    channel = _channel_for_id(cfg.channel_id)
    fallback_enabled = bool(channel and channel.get("shorts_auto_product_fallback_enabled"))
    fallback_search_limit = int(channel.get("shorts_auto_product_search_limit") or 5) if channel else 5
    coupang_access = (os.environ.get("COUPANG_ACCESS_KEY") or "").strip()
    coupang_secret = (os.environ.get("COUPANG_SECRET_KEY") or "").strip()
    match_by_video = {m.video_id: m for m in matches}
    process_items = []
    seen_video: set[str] = set()
    for c in candidates:
        vid = c["video_id"]
        if vid in seen_video:
            continue
        seen_video.add(vid)
        m = match_by_video.get(vid)
        if m is not None:
            process_items.append(
                {
                    "youtube_url": m.youtube_url,
                    "video_id": m.video_id,
                    "plan_product_name": m.plan_product_name,
                    "deep_link": m.deep_link,
                }
            )
        else:
            process_items.append(
                {
                    "youtube_url": c["youtube_url"],
                    "video_id": c["video_id"],
                    "plan_product_name": c["plan_product_name"],
                    "deep_link": "",
                }
            )

    for m in process_items:
        product_name = m["plan_product_name"]
        deep_link = m["deep_link"]
        product = find_product_for_sheet_product_name(db, infl, product_name)
        if product is None:
            if not fallback_enabled:
                log.append(
                    f"[{cfg.channel_id}] 상품 미매칭 스킵 video={m['video_id']} name={product_name!r}"
                )
                continue
            if not coupang_access or not coupang_secret:
                log.append(
                    f"[{cfg.channel_id}] auto_product_skip_reason=missing_coupang_key video={m['video_id']}"
                )
                continue
            log.append(f"[{cfg.channel_id}] auto_product_fallback_start video={m['video_id']}")
            transcript_for_pick = await resolve_transcript_text(
                m["youtube_url"], m["video_id"], youtube_api_key=youtube_api_key
            )
            if not (transcript_for_pick or "").strip():
                log.append(f"[{cfg.channel_id}] auto_product_skip_reason=no_transcript video={m['video_id']}")
                continue
            try:
                keyword = await pick_product_keyword_from_transcript(
                    gemini_api_key,
                    transcript_text=transcript_for_pick,
                    hinted_product_name=product_name,
                )
            except Exception as e:
                log.append(f"[{cfg.channel_id}] auto_product_skip_reason=gemini_pick_fail err={e}")
                continue
            search = await search_products(
                keyword or product_name,
                coupang_access,
                coupang_secret,
                limit=fallback_search_limit,
            )
            if not search.products:
                log.append(
                    f"[{cfg.channel_id}] auto_product_skip_reason=no_coupang_hit keyword={keyword!r}"
                )
                continue
            picked = search.products[0]
            picked_url = str(picked.get("productUrl") or "").strip()
            deeplinks = await generate_deeplinks(
                [picked_url],
                coupang_access,
                coupang_secret,
            )
            picked_dl = str(deeplinks.get(picked_url) or "").strip() or picked_url
            picked_name = str(picked.get("productName") or product_name).strip() or product_name
            picked_price = str(picked.get("price") or "")
            picked_img = str(picked.get("imageUrl") or "")
            log.append(
                f"[{cfg.channel_id}] auto_product_selected keyword={keyword!r} name={picked_name!r}"
            )
            if not dry_run:
                saved_dl = await upsert_product_row_in_sheet(
                    spreadsheet_id=cfg.spreadsheet_id,
                    product_tab=cfg.product_tab,
                    product_range=cfg.product_range,
                    product_name=picked_name,
                    product_url=picked_url,
                    deep_link=picked_dl,
                    price=picked_price,
                    image_url=picked_img,
                    channel_id=cfg.channel_id,
                    product_name_col=cfg.product_name_col,
                    product_deeplink_col=cfg.product_deeplink_col,
                    product_status_col=cfg.product_status_col,
                    product_status_value=cfg.product_status_value,
                )
                log.append(f"[{cfg.channel_id}] auto_product_sheet_append name={picked_name!r}")
                product = upsert_product_in_db(
                    db=db,
                    influencer_slug=infl,
                    product_name=picked_name,
                    product_url=picked_url,
                    price=picked_price,
                    image_url=picked_img,
                )
                log.append(f"[{cfg.channel_id}] auto_product_db_sync product_id={product.id}")
                deep_link = saved_dl or picked_dl
                product_name = picked_name
            else:
                deep_link = picked_dl
                product_name = picked_name
                log.append(f"[{cfg.channel_id}] [dry-run] auto_product_sheet_append 예정 name={picked_name!r}")
                log.append(f"[{cfg.channel_id}] [dry-run] auto_product_db_sync 예정")

        dup = db.scalar(
            select(Review.id).where(
                Review.influencer_slug == infl,
                Review.source_youtube_video_id == m["video_id"],
            )
        )
        if dup is not None:
            log.append(f"[{cfg.channel_id}] 이미 발행됨 video={m['video_id']}")
            continue

        transcript = await resolve_transcript_text(
            m["youtube_url"], m["video_id"], youtube_api_key=youtube_api_key
        )
        if not (transcript or "").strip():
            log.append(f"[{cfg.channel_id}] 자막·메타 없음 스킵 video={m['video_id']}")
            continue

        try:
            draft = await generate_review_from_sheet_transcript(
                gemini_api_key,
                influencer_display=display_name,
                transcript_text=transcript,
                product_name=product_name,
                deeplink=deep_link,
            )
        except Exception as e:
            log.append(f"[{cfg.channel_id}] Gemini 실패 video={m['video_id']}: {e}")
            continue

        if dry_run:
            title = (draft.get("title") or "").strip()
            html = draft.get("html") or ""
            log.append(
                f"[{cfg.channel_id}] [dry-run] video={m['video_id']} product_id={(product.id if product else 0)} title={title!r}"
            )
            preview = html[:3000]
            log.append(f"[{cfg.channel_id}] [dry-run] html_preview:\n{preview}")
            if len(html) > 3000:
                log.append(f"[{cfg.channel_id}] [dry-run] ... (본문 {len(html)}자, 로그 3000자까지만)")
            continue

        review, err = create_review_from_shorts_pipeline(
            db,
            influencer_slug=infl,
            product_id=(product.id if product else None),
            title=draft["title"],
            content_html=draft["html"],
            source_youtube_video_id=m["video_id"],
        )
        if err == "duplicate_video_id":
            log.append(f"[{cfg.channel_id}] 이미 발행됨 video={m['video_id']}")
            continue
        if review is None:
            log.append(f"[{cfg.channel_id}] 발행 실패 video={m['video_id']} err={err}")
            continue
        log.append(
            f"[{cfg.channel_id}] 리뷰 발행 id={review.id} video={m['video_id']} product_id={(product.id if product else 0)}"
        )

    return log
