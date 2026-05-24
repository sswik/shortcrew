#!/usr/bin/env python3
"""쇼츠 시트 트리거 리뷰 파이프라인 (cron 용).

프로젝트 루트에서:

    .venv/bin/python scripts/run_shorts_sheet_reviews.py
    .venv/bin/python scripts/run_shorts_sheet_reviews.py 104
    .venv/bin/python scripts/run_shorts_sheet_reviews.py --dry-run --limit 1 104

- ``--dry-run``: ``reviews`` INSERT 없음. 시트 매칭·자막·Gemini까지는 수행하고 제목·HTML 미리보기만 로그
  (Gemini·YouTube API 쿼터는 사용됨. DB만 오염하지 않음.)
- ``--limit N``: 매칭된 행 중 **앞에서 N건만** 처리(과거 일괄 발행 방지).
  기획 탭 **D열(기본) 날짜 = 오늘(KST 등 ``SHORTS_PLAN_DATE_TZ``)** 인 행만 매칭되므로, 과거 행 일괄 재발행은 D열을 당일로 맞추거나 env/코드를 조정해야 한다.

인자 없음: ``SHORTS_AUTOMATION_ENABLED`` 가 켜진 채널 전부.
마지막 위치 인자: 해당 ``channel_id`` 만.

필요: ``.env`` 의 ``GOOGLE_GEMINI_KEY``, ``YOUTUBE_API_KEY``, ``google-key.json``, 채널별 시트 env.

**매일 한 번(한국 자정)** cron 예시는 ``docs/06_SHORTS_SHEET_REVIEWS.md`` 참고.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def load_env() -> None:
    p = _ROOT / ".env"
    if not p.is_file():
        return
    from dotenv import dotenv_values

    for key, val in dotenv_values(p).items():
        if val is None:
            continue
        cur = os.environ.get(key)
        if cur is None or str(cur).strip() == "":
            os.environ[key] = val


async def _run(
    channel_id: str | None,
    *,
    dry_run: bool,
    limit: int | None,
) -> int:
    gemini = (os.environ.get("GOOGLE_GEMINI_KEY") or "").strip()
    yt = (os.environ.get("YOUTUBE_API_KEY") or "").strip()
    if not gemini:
        print("GOOGLE_GEMINI_KEY 가 없습니다.", file=sys.stderr)
        return 2
    if not yt:
        print("YOUTUBE_API_KEY 가 없습니다.", file=sys.stderr)
        return 2

    from models import SessionLocal

    from app.admin.ops.services.shorts_review_config import (
        iter_shorts_review_configs,
        shorts_config_for_channel_id,
    )
    from app.admin.ops.services.shorts_review_pipeline import run_shorts_review_pipeline_for_channel

    if channel_id:
        cfg = shorts_config_for_channel_id(channel_id)
        if cfg is None:
            print(
                f"채널 {channel_id!r} 에 쇼츠 자동화 설정이 없거나 비활성입니다.",
                file=sys.stderr,
            )
            return 1
        configs = [cfg]
    else:
        configs = iter_shorts_review_configs()
        if not configs:
            print("실행할 채널이 없습니다.", file=sys.stderr)
            return 1

    db = SessionLocal()
    try:
        for cfg in configs:
            lines = await run_shorts_review_pipeline_for_channel(
                db,
                cfg,
                gemini_api_key=gemini,
                youtube_api_key=yt,
                dry_run=dry_run,
                limit=limit,
            )
            for line in lines:
                print(line)
        return 0
    finally:
        db.close()


def main() -> int:
    load_env()
    p = argparse.ArgumentParser(description="쇼츠 시트 트리거 리뷰 자동 발행")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="DB INSERT 없이 매칭·자막·Gemini 결과만 로그",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="처리할 매칭 행 최대 개수(양의 정수)",
    )
    p.add_argument(
        "channel_id",
        nargs="?",
        default=None,
        metavar="CHANNEL_ID",
        help="예: 104. 생략 시 자동화 켜진 채널 전부",
    )
    args = p.parse_args()
    cid = (args.channel_id or "").strip() or None
    lim = args.limit
    if lim is not None and lim < 1:
        print("--limit 은 1 이상의 정수만 사용하세요.", file=sys.stderr)
        return 2
    return asyncio.run(_run(cid, dry_run=args.dry_run, limit=lim))


if __name__ == "__main__":
    raise SystemExit(main())
