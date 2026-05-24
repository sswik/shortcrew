#!/usr/bin/env python3
"""SQLite 스키마 보정 + 로스터 기준 `influencers` 시드(몰 슬러그).

프로젝트 루트에서:

    .venv/bin/python scripts/setup_sqlite_from_roster.py
    .venv/bin/python scripts/setup_sqlite_from_roster.py 103 104 105 106

인자 없음: `get_channels()` 중 `MALL_INFLUENCER_SLUG` 가 있는 채널 전부.
인자 있음: 해당 `channel_id` 만.

`main.py` 는 `create_all` 만 수행한다. 예전 DB는 이 스크립트를 한 번 돌린 뒤 서버를 띄운다.
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


def migrate_sqlite_schema() -> None:
    from sqlalchemy import text

    from models import engine

    if "sqlite" not in str(engine.url).lower():
        print("SQLite 가 아니면 스키마 보정을 건너뜁니다.", file=sys.stderr)
        return

    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(reviews)")).fetchall()}
        if cols and "product_id" not in cols:
            conn.execute(text("ALTER TABLE reviews ADD COLUMN product_id INTEGER"))

        rows = conn.execute(text("PRAGMA table_info(click_logs)")).fetchall()
        if rows:
            cols = {row[1] for row in rows}
            if "product_id" not in cols:
                conn.execute(text("ALTER TABLE click_logs ADD COLUMN product_id INTEGER NOT NULL DEFAULT 0"))
            if "product_ref" in cols:
                conn.execute(
                    text(
                        "UPDATE click_logs SET product_ref = CAST(product_id AS TEXT) "
                        "WHERE product_ref IS NULL OR TRIM(CAST(product_ref AS TEXT)) = ''"
                    )
                )
                try:
                    conn.execute(text("ALTER TABLE click_logs DROP COLUMN product_ref"))
                except Exception:
                    conn.execute(text("DROP TABLE IF EXISTS click_logs__new"))
                    conn.execute(
                        text(
                            "CREATE TABLE click_logs__new ("
                            "id INTEGER NOT NULL PRIMARY KEY,"
                            "influencer_slug VARCHAR(100) NOT NULL,"
                            "product_id INTEGER NOT NULL,"
                            "created_at DATETIME"
                            ")"
                        )
                    )
                    conn.execute(
                        text(
                            "INSERT INTO click_logs__new (id, influencer_slug, product_id, created_at) "
                            "SELECT id, influencer_slug, "
                            "CASE WHEN IFNULL(product_id, 0) != 0 THEN product_id "
                            "WHEN TRIM(COALESCE(CAST(product_ref AS TEXT), '')) GLOB '[0-9]*' "
                            "THEN CAST(TRIM(CAST(product_ref AS TEXT)) AS INTEGER) "
                            "ELSE 0 END, "
                            "created_at FROM click_logs"
                        )
                    )
                    conn.execute(text("DROP TABLE click_logs"))
                    conn.execute(text("ALTER TABLE click_logs__new RENAME TO click_logs"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_click_logs_product_id ON click_logs (product_id)"))

        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(influencers)")).fetchall()}
        if cols and "shop_path_slug" not in cols:
            conn.execute(text("ALTER TABLE influencers ADD COLUMN shop_path_slug VARCHAR(120)"))
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_influencers_shop_path_slug_partial "
                    "ON influencers (shop_path_slug) WHERE shop_path_slug IS NOT NULL"
                )
            )
        if cols:
            if "bio" not in cols:
                conn.execute(text("ALTER TABLE influencers ADD COLUMN bio TEXT"))
            if "youtube_url" not in cols:
                conn.execute(text("ALTER TABLE influencers ADD COLUMN youtube_url VARCHAR(500) DEFAULT ''"))
            if "instagram_url" not in cols:
                conn.execute(text("ALTER TABLE influencers ADD COLUMN instagram_url VARCHAR(500) DEFAULT ''"))
            if "tiktok_url" not in cols:
                conn.execute(text("ALTER TABLE influencers ADD COLUMN tiktok_url VARCHAR(500) DEFAULT ''"))
            if "cover_image" not in cols:
                conn.execute(text("ALTER TABLE influencers ADD COLUMN cover_image VARCHAR(500) DEFAULT ''"))
            if "profile_meta_json" not in cols:
                conn.execute(text("ALTER TABLE influencers ADD COLUMN profile_meta_json TEXT"))
            if "mall_theme_json" not in cols:
                conn.execute(text("ALTER TABLE influencers ADD COLUMN mall_theme_json TEXT"))

        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(reviews)")).fetchall()}
        if cols and "source_youtube_video_id" not in cols:
            conn.execute(text("ALTER TABLE reviews ADD COLUMN source_youtube_video_id VARCHAR(32)"))
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(reviews)")).fetchall()}
        if cols and "sheet_product_title" not in cols:
            conn.execute(text("ALTER TABLE reviews ADD COLUMN sheet_product_title VARCHAR(255)"))
        if cols and "sheet_product_deeplink" not in cols:
            conn.execute(text("ALTER TABLE reviews ADD COLUMN sheet_product_deeplink VARCHAR(500)"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_reviews_influencer_youtube_video "
                "ON reviews (influencer_slug, source_youtube_video_id)"
            )
        )


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
    p = argparse.ArgumentParser(description="SQLite 보정 + 로스터 기준 influencers 시드")
    p.add_argument(
        "channels",
        nargs="*",
        metavar="CHANNEL_ID",
        help="예: 103 104 105. 생략 시 MALL_INFLUENCER_SLUG 가 있는 채널 전부",
    )
    args = p.parse_args()
    channel_ids: set[str] | None = set(args.channels) if args.channels else None

    from models import Base, engine

    migrate_sqlite_schema()
    Base.metadata.create_all(bind=engine)
    seed_influencers(channel_ids)
    print("완료: 스키마 보정 + create_all + influencers 시드")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
