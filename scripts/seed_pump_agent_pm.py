#!/usr/bin/env python3
"""Agent PM 몰(`/agent-pm`, 채널 100) — `pumps` 행 1개를 넣거나 갱신한다(여러 번 실행해도 안전).

공개 몰 `/{name_slug}` 은 이 행(제목·소개·테마)이 있어야 열린다. 상품은 채널 100 상품탭
(`CHANNEL_100_FILE_ID`/`CHANNEL_100_TAB`)에서 읽는다 — 쿠파스 «번호 카드» 몰(app/client/mall_kupas.py).

운영 서버(컨테이너 안)에서 1회:

    docker compose exec shortcrew python scripts/seed_pump_agent_pm.py

`--dry-run` 이면 DB 를 바꾸지 않고 넣을 값만 출력한다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

SLUG = "agent-pm"
DISPLAY_NAME = "Agent PM 업무 시간 계산서"
BIO = "새는 업무 시간을 돈으로 계산합니다"
YOUTUBE_URL = "https://www.youtube.com/@next_agent_pm"
INSTAGRAM_URL = "https://www.instagram.com/next_agent_pm/"
# 딥네이비 + 민트 + 앰버
THEME = {
    "background": "#0B1A2F",
    "card": "#13243D",
    "accent": "#3ED6C0",
    "accentDark": "#2BB3A0",
    "textMain": "#F5F7FA",
    "textSub": "#9DB0C7",
    "border": "#22385A",
    "cta": "#F5B83D",
    "ctaHover": "#E0A52E",
}


def load_env() -> None:
    p = _ROOT / ".env"
    if not p.is_file():
        return
    from dotenv import dotenv_values

    for key, val in dotenv_values(p).items():
        if val is not None and not (os.environ.get(key) or "").strip():
            os.environ[key] = val


def main() -> int:
    ap = argparse.ArgumentParser(description="Agent PM 몰 pumps 행 시드")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    values = {
        "display_name": DISPLAY_NAME,
        "bio": BIO,
        "youtube_url": YOUTUBE_URL,
        "instagram_url": INSTAGRAM_URL,
        "mall_theme_json": json.dumps(THEME, ensure_ascii=False),
    }
    if args.dry_run:
        print(json.dumps({"name_slug": SLUG, **values}, ensure_ascii=False, indent=2))
        return 0

    load_env()
    from sqlalchemy import select

    from models import Pump, SessionLocal

    with SessionLocal() as db:
        row = db.scalar(select(Pump).where(Pump.name_slug == SLUG))
        action = "updated"
        if row is None:
            row = Pump(name_slug=SLUG, profile_image="", cover_image="", tiktok_url="")
            action = "inserted"
        for k, v in values.items():
            setattr(row, k, v)
        db.add(row)
        db.commit()
        print(f"{action}: pumps.name_slug={SLUG} id={row.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
