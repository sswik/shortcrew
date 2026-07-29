"""shortcrew 내부 큐레이션 스케줄러 (n8n 의존 없음).

매일 지정 시각(KST)에 커머스 채널 1개를 로테이션 큐레이션 → 상품 시트 적재(+옵션 블로그).
n8n 이 죽어도 앱이 자체적으로 돌린다. 단일 워커 전제(uvicorn 1프로세스).

env
---
- `CURATION_SCHEDULER_ENABLED` : "1"이면 켬(기본 꺼짐 — 개발/테스트 안전)
- `CURATION_SCHEDULER_HOUR`    : 실행 시각(0~23, KST, 기본 8)
- `CURATION_AUTO_BLOG`         : "1"이면 큐레이션 상품마다 블로그 자동생성(Gemini 부하 큼, 기본 꺼짐)

Gemini 한도 보호: 하루 1채널(day-of-year 로테이션). 실패는 로그만, 앱은 안 죽는다.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))


def _truthy(key: str) -> bool:
    return (os.environ.get(key) or "").strip().lower() in ("1", "true", "yes", "on")


def _hour() -> int:
    try:
        h = int((os.environ.get("CURATION_SCHEDULER_HOUR") or "8").strip())
    except ValueError:
        return 8
    return h if 0 <= h <= 23 else 8


def curation_channels() -> list[str]:
    """큐레이션 로테이션 대상.

    env `CURATION_SCHEDULER_CHANNELS`(쉼표구분)가 있으면 그 채널만(예: 인플루언서 02,03,04).
    없으면 상품시트가 설정된 전 커머스 채널(get_channels 순서)."""
    override = (os.environ.get("CURATION_SCHEDULER_CHANNELS") or "").strip()
    if override:
        return [c.strip() for c in override.split(",") if c.strip()]
    from app.admin.ops.channels import get_channels

    return [
        (c.get("channel_id") or "").strip()
        for c in get_channels()
        if (c.get("google_sheet_id") or "").strip()
    ]


def todays_channel(channels: list[str] | None = None) -> str | None:
    chs = channels if channels is not None else curation_channels()
    if not chs:
        return None
    doy = datetime.now(_KST).timetuple().tm_yday
    return chs[doy % len(chs)]


async def run_curation_once(
    channel_id: str | None = None, *, auto_blog: bool | None = None, max_items: int | None = None
) -> dict:
    """1채널 큐레이션 실행(내부 직접 호출). channel_id 없으면 오늘의 채널.

    max_items: 이번 실행 상품 개수. None 이면 env(CURATION_MAX_ITEMS, 증분 기본). 초기시딩은 20 등 명시.
    """
    from app.admin.ops.routes.bridge import CurateBody, curate_products
    from models import SessionLocal

    cid = (channel_id or todays_channel() or "").strip()
    if not cid:
        logger.warning("curation_scheduler: 대상 채널 없음")
        return {"skipped": "no channel"}
    ab = _truthy("CURATION_AUTO_BLOG") if auto_blog is None else auto_blog
    body = CurateBody(channel_id=cid, dry_run=False, auto_blog=ab, max_items=max_items)
    from app.admin.ops.services import discord_notify

    try:
        with SessionLocal() as db:
            result = await curate_products(body, db=db, _=None)
    except Exception as e:  # 큐레이션 실패 → 통합 실패 알림 후 재전파
        await discord_notify.notify(
            f"🔴 상품 큐레이션 실패 [{cid}]: {str(e)[:200]}",
            env_key="DISCORD_WEBHOOK_FAIL",
        )
        raise
    written = result.get("written_to_sheet") or 0
    blogs = result.get("blogs_created") or 0
    logger.info(
        "curation_scheduler done channel=%s written=%s blogs=%s", cid, written, blogs,
    )
    # 생성 성공(상품 큐레이션 + 블로그 글 생성) → 콘텐츠 채널
    await discord_notify.notify(
        f"🛒 상품 큐레이션 완료 [{cid}] 상품 {written}개 · 블로그 {blogs}개",
        env_key="DISCORD_WEBHOOK_CONTENT",
    )
    # 블로그 생성 중 개별 실패(이미지 없음 등 skip 제외, 실제 error 만) → 실패 채널
    picks = result.get("picks")
    blog_errs: list[str] = []
    if isinstance(picks, list):
        for pk in picks:
            b = pk.get("blog") if isinstance(pk, dict) else None
            if isinstance(b, str) and b.startswith("error"):
                blog_errs.append(b)
    if blog_errs:
        await discord_notify.notify(
            f"🔴 블로그 글 발행 실패 [{cid}] {len(blog_errs)}건: {blog_errs[0][:150]}",
            env_key="DISCORD_WEBHOOK_FAIL",
        )
    return result


async def _loop() -> None:
    while True:
        now = datetime.now(_KST)
        nxt = now.replace(hour=_hour(), minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        await asyncio.sleep(max(1.0, (nxt - now).total_seconds()))
        try:
            await run_curation_once()
        except Exception as e:  # 실패해도 루프·앱 유지
            logger.exception("curation_scheduler run failed: %s", e)


def start() -> None:
    """앱 startup 에서 호출. env 로 켜졌을 때만 백그라운드 태스크 기동."""
    if not _truthy("CURATION_SCHEDULER_ENABLED"):
        logger.info("curation_scheduler disabled (CURATION_SCHEDULER_ENABLED != 1)")
        return
    try:
        asyncio.get_running_loop().create_task(_loop())
        logger.info(
            "curation_scheduler started (hour=%s KST, auto_blog=%s, channels=%d)",
            _hour(),
            _truthy("CURATION_AUTO_BLOG"),
            len(curation_channels()),
        )
    except RuntimeError:
        logger.warning("curation_scheduler: 러닝 루프 없음 — 기동 스킵")
