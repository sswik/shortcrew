"""기존 SQLite(`database.db`) 데이터를 `.env` 의 DATABASE_URL(MySQL crews)로 이관한다.

사용:
    .venv/bin/python scripts/migrate_sqlite_to_mysql.py
    .venv/bin/python scripts/migrate_sqlite_to_mysql.py --sqlite ./database.db

- 대상(target)은 models.engine(= .env DATABASE_URL). MySQL 이 아니면 중단한다.
- target 테이블을 create_all 로 만들고, 재실행 가능하도록 기존 행을 비운 뒤 PK 보존 복사한다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from models import Base, engine as target_engine  # noqa: E402

# FK 의존 순서: 부모 → 자식 (insert), 역순 (delete)
INSERT_ORDER = ["influencers", "products", "reviews", "click_logs", "dm_automations"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", default=str(_ROOT / "database.db"), help="원본 SQLite 파일 경로")
    args = ap.parse_args()

    if target_engine.dialect.name == "sqlite":
        print("[중단] 대상(DATABASE_URL)이 여전히 sqlite 다. .env 의 DATABASE_URL 을 MySQL 로 설정하라.")
        return 2

    src_path = Path(args.sqlite)
    if not src_path.is_file():
        print(f"[중단] 원본 SQLite 없음: {src_path}")
        return 2

    src = create_engine(f"sqlite:///{src_path}")

    print(f"원본: sqlite:///{src_path}")
    print(f"대상: {target_engine.url.render_as_string(hide_password=True)}")

    # 1) 대상 스키마 생성
    Base.metadata.create_all(target_engine)

    tables = {t.name: t for t in Base.metadata.sorted_tables}

    # 2) 재실행 안전: 대상 기존 행 비우기(자식 → 부모)
    with target_engine.begin() as tconn:
        try:
            tconn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
        except Exception:
            pass
        for name in reversed(INSERT_ORDER):
            tconn.execute(tables[name].delete())
        try:
            tconn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")
        except Exception:
            pass

    # 3) 부모 → 자식 순으로 복사(PK 보존)
    total = 0
    for name in INSERT_ORDER:
        table = tables[name]
        with src.connect() as sconn:
            rows = [dict(r._mapping) for r in sconn.execute(table.select())]
        if not rows:
            print(f"  {name:16} 0건")
            continue
        with target_engine.begin() as tconn:
            tconn.execute(table.insert(), rows)
        total += len(rows)
        print(f"  {name:16} {len(rows)}건 이관")

    # 4) 검증
    print("--- 대상 행수 확인 ---")
    with target_engine.connect() as tconn:
        for name in INSERT_ORDER:
            n = tconn.exec_driver_sql(f"SELECT COUNT(*) FROM {name}").scalar()
            print(f"  {name:16} {n}건")
    print(f"완료. 총 {total}건 이관.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
