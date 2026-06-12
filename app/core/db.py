"""DB 세션 의존성·스키마 마이그레이션. models 의 engine/SessionLocal/Base 를 감싼다.

`run_migrations()` 는 앱 부팅 시 1회 호출한다(create_all + SQLite 한정 컬럼 보정)."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import Base, SessionLocal, engine


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_click_log_schema() -> None:
    """기존 SQLite DB에 click_logs 신규 컬럼을 안전하게 추가한다."""
    if engine.dialect.name != "sqlite":
        return  # MySQL 등은 create_all 이 전체 스키마를 만들므로 PRAGMA 패치 불필요
    with engine.begin() as conn:
        cols = {
            str(row[1]).strip().lower()
            for row in conn.execute(text("PRAGMA table_info(click_logs)")).fetchall()
        }
        if "raw_product_ref" not in cols:
            conn.execute(text("ALTER TABLE click_logs ADD COLUMN raw_product_ref VARCHAR(120)"))
        if "product_name_snapshot" not in cols:
            conn.execute(text("ALTER TABLE click_logs ADD COLUMN product_name_snapshot VARCHAR(255)"))
        if "deep_link_snapshot" not in cols:
            conn.execute(text("ALTER TABLE click_logs ADD COLUMN deep_link_snapshot VARCHAR(1200)"))
        if "client_user_agent" not in cols:
            conn.execute(text("ALTER TABLE click_logs ADD COLUMN client_user_agent VARCHAR(512)"))
        if "page_url" not in cols:
            conn.execute(text("ALTER TABLE click_logs ADD COLUMN page_url VARCHAR(800)"))
        if "referrer_snapshot" not in cols:
            conn.execute(text("ALTER TABLE click_logs ADD COLUMN referrer_snapshot VARCHAR(600)"))


def _ensure_influencer_v2_columns() -> None:
    """SQLite: profile_meta_json, mall_theme_json for ShortCrew V2."""
    if engine.dialect.name != "sqlite":
        return  # MySQL 등은 create_all 이 전체 스키마를 만들므로 PRAGMA 패치 불필요
    with engine.begin() as conn:
        cols = {
            str(row[1]).strip().lower()
            for row in conn.execute(text("PRAGMA table_info(influencers)")).fetchall()
        }
        if not cols:
            return
        if "profile_meta_json" not in cols:
            conn.execute(text("ALTER TABLE influencers ADD COLUMN profile_meta_json TEXT"))
        if "mall_theme_json" not in cols:
            conn.execute(text("ALTER TABLE influencers ADD COLUMN mall_theme_json TEXT"))


def run_migrations() -> None:
    """create_all + (SQLite 한정) 컬럼 보정. 앱 부팅 시 1회 호출."""
    Base.metadata.create_all(bind=engine)
    _ensure_click_log_schema()
    _ensure_influencer_v2_columns()
