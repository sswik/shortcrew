"""숏몰(short-mall) SQLite `pumps` → 숏크루 MySQL `pumps` 이관 (00식 통합 Phase 2).

- 숏몰 `database.db` 의 pumps 31행(소개·bio·프로필·SNS·테마)을 그대로 upsert.
- 채널 02/03/04(골프·테니스·쇼핑)는 숏몰에 없으므로 숏크루 `influencers`(오세련픽/왕세림픽/한소율픽) 값으로 author.
- name_slug 는 채널 `mall_pump_slug` 와 일치(예: homecam·tech·golf·health-pump).

실행: `.venv/bin/python scripts/migrate_pumps_from_shortmall.py`
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.db import run_migrations  # noqa: E402
from models import Influencer, Pump, SessionLocal  # noqa: E402

SHORTMALL_DB = "/home/ejsv/projects/sswik/short-mall/database.db"

_PUMP_COLS = (
    "name_slug",
    "shop_path_slug",
    "display_name",
    "profile_image",
    "bio",
    "youtube_url",
    "instagram_url",
    "tiktok_url",
    "cover_image",
    "mall_theme_json",
)

# 인플루언서 3채널: name_slug → (기존 influencers name_slug)
_INFLUENCER_AUTHOR = {"golf": "golf", "tennis": "tennis", "shopping": "shopping"}


def _rows_from_shortmall() -> list[dict]:
    conn = sqlite3.connect(SHORTMALL_DB)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(f"select {', '.join(_PUMP_COLS)} from pumps")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _upsert(session, data: dict) -> str:
    existing = session.query(Pump).filter(Pump.name_slug == data["name_slug"]).one_or_none()
    if existing is None:
        session.add(Pump(**data))
        return "insert"
    for k, v in data.items():
        if k != "name_slug":
            setattr(existing, k, v)
    return "update"


def main() -> None:
    run_migrations()  # pumps 테이블 생성(create_all, checkfirst)
    sm_rows = _rows_from_shortmall()
    ins = upd = 0
    with SessionLocal() as session:
        # 1) 숏몰 펌프 31행
        for row in sm_rows:
            data = {c: row.get(c) for c in _PUMP_COLS}
            data["profile_image"] = data.get("profile_image") or ""
            for k in ("youtube_url", "instagram_url", "tiktok_url", "cover_image"):
                data[k] = data.get(k) or ""
            r = _upsert(session, data)
            ins += r == "insert"
            upd += r == "update"
        # 2) 인플루언서 3채널 author (influencers 에서 소개 값 가져옴)
        for pump_slug, infl_slug in _INFLUENCER_AUTHOR.items():
            infl = session.query(Influencer).filter(Influencer.name_slug == infl_slug).one_or_none()
            data = {
                "name_slug": pump_slug,
                "shop_path_slug": None,
                "display_name": (infl.display_name if infl else pump_slug),
                "profile_image": (infl.profile_image if infl else "") or "",
                "bio": (infl.bio if infl else None),
                "youtube_url": (infl.youtube_url if infl else "") or "",
                "instagram_url": (infl.instagram_url if infl else "") or "",
                "tiktok_url": (infl.tiktok_url if infl else "") or "",
                "cover_image": (infl.cover_image if infl else "") or "",
                "mall_theme_json": (infl.mall_theme_json if infl else None),
            }
            r = _upsert(session, data)
            ins += r == "insert"
            upd += r == "update"
        session.commit()
        total = session.query(Pump).count()
    print(f"이관 완료: insert {ins}, update {upd} | pumps 총 {total}행")


if __name__ == "__main__":
    main()
