"""DB 세션 의존성·스키마 마이그레이션. models 의 engine/SessionLocal/Base 를 감싼다.

`run_migrations()` 는 앱 부팅 시 1회 호출한다(create_all)."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from models import Base, SessionLocal, engine


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations() -> None:
    """create_all. 앱 부팅 시 1회 호출(MySQL 이 전체 스키마를 생성)."""
    Base.metadata.create_all(bind=engine)
