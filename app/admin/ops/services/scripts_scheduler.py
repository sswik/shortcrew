"""shortcrew 내부 '후기→대본 브리지' 스케줄러 (n8n 의존 없음).

매주 지정 요일·시각(KST)에 파일럿 채널(골프02·테니스03)의 상품탭 상품을
후기형/폴백형 대본으로 만들어 시트1에 적재한다. AFxx 발행이 그걸 소비.
n8n 이 죽어도 앱이 자체적으로 돌리며, 실패는 로그+디스코드 경보만 — 앱은 안 죽는다.

env
---
- `SCRIPTS_SCHEDULER_ENABLED` : "1"이면 켬(기본 꺼짐 — 안전)
- `SCRIPTS_SCHEDULER_HOUR`    : 실행 시각(0~23, KST, 기본 8) — AFxx 발행(11~12시)보다 이르게
- `SCRIPTS_SCHEDULER_WEEKDAY` : 실행 요일(0=월 ~ 6=일, 기본 0)
- `SCRIPTS_SCHEDULER_COUNT`   : 채널당 편수(기본 7 = 요일당 1편)
- `SCRIPTS_SCHEDULER_CHANNELS`: 대상 채널(기본 "02,03")

Gemini 부하: 주 1회 · 채널당 COUNT 콜(기본 7×2=14)로 작다. 단일 워커 전제.
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


def _int_env(key: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int((os.environ.get(key) or str(default)).strip())
    except ValueError:
        return default
    return v if lo <= v <= hi else default


def _hour() -> int:
    return _int_env("SCRIPTS_SCHEDULER_HOUR", 8, 0, 23)


def _weekday() -> int:
    return _int_env("SCRIPTS_SCHEDULER_WEEKDAY", 0, 0, 6)


def _count() -> int:
    return _int_env("SCRIPTS_SCHEDULER_COUNT", 7, 1, 30)


def _curate_items() -> int:
    """대본 생성 전 선행 큐레이션 상품 수. dedup 감안해 count 보다 넉넉히(기본 12).

    발행속도(1일 1편=주 7편)를 대본이 따라가려면 매주 새 상품이 그만큼 공급돼야 한다.
    큐레이션→대본을 한 세트로 돌려 상품 공급이 대본 소비를 따라가게 한다(빵꾸 방지)."""
    return _int_env("SCRIPTS_SCHEDULER_CURATE_ITEMS", max(_count() + 5, 12), 0, 50)


def _channels() -> list[str]:
    raw = (os.environ.get("SCRIPTS_SCHEDULER_CHANNELS") or "02,03").strip()
    return [c.strip() for c in raw.split(",") if c.strip()]


def _next_run(now: datetime) -> datetime:
    """다음 실행시각 = 이번주/다음주 지정 요일의 지정 시각(KST)."""
    target_h, target_wd = _hour(), _weekday()
    nxt = now.replace(hour=target_h, minute=0, second=0, microsecond=0)
    days_ahead = (target_wd - now.weekday()) % 7
    nxt += timedelta(days=days_ahead)
    if nxt <= now:  # 오늘이 그 요일이지만 시각이 지났으면 다음주
        nxt += timedelta(days=7)
    return nxt


async def run_scripts_once() -> dict:
    """대상 채널 전부 1회 실행(내부 직접 호출). 채널별 실패는 격리."""
    from app.admin.ops.routes.bridge_scripts import ScriptBody, build_review_scripts
    from app.admin.ops.services import discord_notify
    from app.admin.ops.services.curation_scheduler import run_curation_once
    from models import SessionLocal

    count = _count()
    curate_n = _curate_items()
    summary: list[str] = []
    for cid in _channels():
        # ① 선행 큐레이션 — 새 상품 공급(발행속도 매칭, 빵꾸 방지). 실패해도 대본생성은 시도.
        if curate_n > 0:
            try:
                cur = await run_curation_once(cid, auto_blog=False, max_items=curate_n)
                logger.info("scripts_scheduler curate %s: +%s 상품", cid, cur.get("written_to_sheet"))
            except Exception as e:
                logger.warning("scripts_scheduler curate %s 실패(대본생성은 진행): %s", cid, str(e)[:80])
        # ② 대본 생성
        body = ScriptBody(channel_id=cid, count=count, dry_run=False)
        try:
            with SessionLocal() as db:
                res = await build_review_scripts(body, db=db, _=None)
            summary.append(
                f"{res.get('mall_slug', cid)} {res.get('written', 0)}편"
                f"(후기 {res.get('review_based', 0)}·폴백 {res.get('fallback', 0)})"
            )
        except Exception as e:  # 채널 하나 실패해도 나머지·앱은 계속
            logger.exception("scripts_scheduler channel %s failed: %s", cid, e)
            summary.append(f"{cid} 실패: {str(e)[:80]}")
            await discord_notify.notify(f"🔴 후기대본 브리지 실패 [{cid}]: {str(e)[:200]}")

    msg = "📝 후기대본 브리지 완료 — " + " / ".join(summary)
    await discord_notify.notify(msg)
    logger.info(msg)
    return {"summary": summary}


async def _loop() -> None:
    while True:
        now = datetime.now(_KST)
        nxt = _next_run(now)
        await asyncio.sleep(max(1.0, (nxt - now).total_seconds()))
        try:
            await run_scripts_once()
        except Exception as e:  # 실패해도 루프·앱 유지
            logger.exception("scripts_scheduler run failed: %s", e)


def start() -> None:
    """앱 startup 에서 호출. env 로 켜졌을 때만 백그라운드 태스크 기동."""
    if not _truthy("SCRIPTS_SCHEDULER_ENABLED"):
        logger.info("scripts_scheduler disabled (SCRIPTS_SCHEDULER_ENABLED != 1)")
        return
    try:
        asyncio.get_running_loop().create_task(_loop())
        logger.info(
            "scripts_scheduler started (weekday=%d hour=%d KST, channels=%s, count=%d)",
            _weekday(), _hour(), ",".join(_channels()), _count(),
        )
    except RuntimeError:
        logger.warning("scripts_scheduler: 러닝 루프 없음 — 기동 스킵")
