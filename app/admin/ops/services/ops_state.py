"""스케줄러 영속 상태 + 분산 잠금 (DB 백엔드, 파일 폴백).

왜 DB 인가
---------
기존엔 `logs/*.json` 파일에 상태를 뒀다. 로컬 단일 컨테이너에선 `./logs` 볼륨이
있어 문제가 없었지만, Cloud Run 은 파일시스템이 휘발성이고 인스턴스가 수시로
교체된다. 상태가 사라지면:

- `ig_backfill_daily` 유실 → 하루 상한이 0 으로 리셋 → 같은 날 몇 배로 과발행
- `ig_tokens` 유실 → 자동갱신된 토큰이 사라지고 `.env` 의 낡은 토큰으로 회귀

게다가 오토스케일로 인스턴스가 둘 이상이면 같은 영상을 두 번 올릴 수 있다.
그래서 상태는 `ops_state`, 동시성 제어는 `ops_lock` 테이블로 옮겼다.

이전 기간에도 안전한 이유
----------------------
로컬 컨테이너와 Cloud Run 이 같은 TiDB 를 보므로 상태(일일 카운트·토큰)가 공유된다.
둘 다 켜져 있어도 상한을 함께 소진하고, 잠금 덕에 같은 슬롯이 겹치지 않는다.

폴백
----
`OPS_STATE_BACKEND=file` 이거나 DB 접근이 실패하면 기존 파일 경로를 쓴다.
DB 가 없는 환경(테스트·스크립트)에서 import 만으로 죽지 않게 하기 위함이다.
"""
from __future__ import annotations

import json
import logging
import os
import socket
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_DEFAULT_LOCK_TTL_S = 600


def _use_db() -> bool:
    backend = (os.environ.get("OPS_STATE_BACKEND") or "db").strip().lower()
    return backend != "file"


def _holder() -> str:
    # Cloud Run 은 K_REVISION 을 준다. 로컬은 호스트명.
    rev = (os.environ.get("K_REVISION") or "").strip()
    return f"{rev or socket.gethostname()}:{os.getpid()}"[:128]


# ---------------------------------------------------------------- 상태(JSON)

def load_json(key: str, file_fallback: str) -> dict:
    """상태 1건 읽기. DB 우선, 실패 시 파일."""
    if _use_db():
        try:
            from models import OpsState, SessionLocal

            with SessionLocal() as s:
                row = s.get(OpsState, key)
                if row is not None:
                    return json.loads(row.v or "{}") or {}
                return {}
        except Exception as e:
            logger.warning("ops_state: DB 읽기 실패 key=%s (%s) → 파일 폴백", key, str(e)[:80])
    try:
        with open(file_fallback, encoding="utf-8") as f:
            return json.load(f) or {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def save_json(key: str, data: dict, file_fallback: str) -> None:
    """상태 1건 쓰기. DB 우선, 실패 시 파일."""
    if _use_db():
        try:
            from models import OpsState, SessionLocal

            payload = json.dumps(data, ensure_ascii=False)
            with SessionLocal() as s:
                row = s.get(OpsState, key)
                if row is None:
                    s.add(OpsState(k=key, v=payload))
                else:
                    row.v = payload
                s.commit()
            return
        except Exception as e:
            logger.warning("ops_state: DB 쓰기 실패 key=%s (%s) → 파일 폴백", key, str(e)[:80])
    try:
        os.makedirs(os.path.dirname(file_fallback) or ".", exist_ok=True)
        with open(file_fallback, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError as e:
        logger.warning("ops_state: 파일 저장 실패 %s (%s)", file_fallback, str(e)[:80])


# ---------------------------------------------------------------- 분산 잠금

def acquire_lock(name: str, ttl_s: int = _DEFAULT_LOCK_TTL_S) -> bool:
    """잠금 획득(성공 True). DB 를 못 쓰면 True(= 단일 인스턴스로 간주)."""
    if not _use_db():
        return True
    try:
        from models import OpsLock, SessionLocal

        now = datetime.utcnow()
        with SessionLocal() as s:
            row = s.get(OpsLock, name)
            if row is None:
                s.add(OpsLock(name=name, holder=_holder(), acquired_at=now,
                              expires_at=now + timedelta(seconds=ttl_s)))
                s.commit()
                return True
            if row.expires_at and row.expires_at > now:
                return False  # 다른 인스턴스가 보유 중
            # 만료된 잠금은 뺏는다(프로세스가 죽어 해제 못 한 경우).
            row.holder = _holder()
            row.acquired_at = now
            row.expires_at = now + timedelta(seconds=ttl_s)
            s.commit()
            return True
    except Exception as e:
        # 잠금을 못 쓰더라도 발행 자체를 막지는 않는다(기존 동작 유지).
        logger.warning("ops_state: 잠금 획득 실패 %s (%s) → 잠금 없이 진행", name, str(e)[:80])
        return True


def release_lock(name: str) -> None:
    if not _use_db():
        return
    try:
        from models import OpsLock, SessionLocal

        with SessionLocal() as s:
            row = s.get(OpsLock, name)
            if row is not None and row.holder == _holder():
                s.delete(row)
                s.commit()
    except Exception as e:
        logger.warning("ops_state: 잠금 해제 실패 %s (%s)", name, str(e)[:80])


def import_file_once(key: str, file_fallback: str) -> bool:
    """DB 에 아직 없고 파일에만 있으면 1회 이관. 이관했으면 True."""
    if not _use_db():
        return False
    try:
        from models import OpsState, SessionLocal

        with SessionLocal() as s:
            if s.get(OpsState, key) is not None:
                return False
        with open(file_fallback, encoding="utf-8") as f:
            data = json.load(f) or {}
    except (FileNotFoundError, ValueError, OSError):
        return False
    except Exception:
        return False
    save_json(key, data, file_fallback)
    logger.info("ops_state: %s 파일→DB 이관 (%d개 키)", key, len(data))
    return True
