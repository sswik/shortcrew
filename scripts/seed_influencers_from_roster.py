#!/usr/bin/env python3
"""로스터 기준 `influencers` 시드(몰 슬러그). DB 무관(현재 운영: MySQL crews).

프로젝트 루트에서:

    .venv/bin/python scripts/seed_influencers_from_roster.py
    .venv/bin/python scripts/seed_influencers_from_roster.py 103 104 105 106

인자 없음: `get_channels()` 중 `MALL_INFLUENCER_SLUG` 가 있는 채널 전부.
인자 있음: 해당 `channel_id` 만.

채널 추가 시 이 스크립트로 influencers 행을 시드한다(create_all + 시드).
"""
from __future__ import annotations

import argparse
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


def seed_influencers(channel_ids: set[str] | None) -> None:
    from sqlalchemy import func, select

    from app.admin.ops.channels import get_channels
    from app.client.mall_sheet import _mall_influencer_aliases
    from models import Influencer, SessionLocal

    with SessionLocal() as db:
        soccer = db.scalar(select(Influencer).where(Influencer.name_slug == "soccer"))
        if soccer is not None:
            p = (soccer.profile_image or "").strip()
            if not p or "inf-1.png" in p:
                soccer.profile_image = "/static/images/influencers/inf-201.png"
                db.add(soccer)

        for ch in get_channels():
            cid = (ch.get("channel_id") or "").strip()
            if not cid:
                continue
            if channel_ids is not None and cid not in channel_ids:
                continue
            aliases = _mall_influencer_aliases(ch)
            if not aliases:
                continue
            img = f"/static/images/influencers/inf-{cid}.png"
            raw_name = (ch.get("name") or "").strip()
            display = raw_name.split("(", 1)[0].strip() or min(aliases)
            for slug in sorted(aliases):
                slug_l = slug.lower()
                row = db.scalar(select(Influencer).where(func.lower(Influencer.name_slug) == slug_l))
                if row is None:
                    db.add(
                        Influencer(
                            name_slug=slug_l,
                            shop_path_slug=None,
                            display_name=display,
                            profile_image=img,
                        )
                    )
                else:
                    row.profile_image = img
                    if not (row.display_name or "").strip():
                        row.display_name = display
                    db.add(row)
        db.commit()


def main() -> int:
    load_env()
    p = argparse.ArgumentParser(description="로스터 기준 influencers 시드")
    p.add_argument(
        "channels",
        nargs="*",
        metavar="CHANNEL_ID",
        help="예: 103 104 105. 생략 시 MALL_INFLUENCER_SLUG 가 있는 채널 전부",
    )
    args = p.parse_args()
    channel_ids: set[str] | None = set(args.channels) if args.channels else None

    from models import Base, engine

    Base.metadata.create_all(bind=engine)
    seed_influencers(channel_ids)
    print("완료: create_all + influencers 시드")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
