"""IG 장기 액세스 토큰 자동갱신 스케줄러 (shortcrew 내부, n8n 무관).

배경
----
Instagram Login API 토큰(`IGA…`)은 **장기 60일**이며, 만료 전 `refresh_access_token`으로
연장할 수 있으나 **만료된 뒤엔 갱신 불가(재로그인 필요)**. 아무도 주기적으로 refresh하지
않으면 60일마다 죽는다(골프·테니스·nature가 이렇게 죽었음).

이 스케줄러가 **유효한 전 채널 토큰을 40일 주기로 자동 refresh**(60일 만료 전 20일 버퍼)
→ 다시는 만료되지 않게 한다.

토큰 지속화
----------
refresh한 새 토큰을 **파일 저장소**(`logs/ig_tokens.json`, 컨테이너 `/app/logs`)에 저장하고,
`_ig_account`(dm.py)가 이 저장소를 **env보다 우선** 읽는다. env는 최초 fallback.

env
---
- IG_TOKEN_REFRESH_ENABLED    : "1"이면 켬(기본 꺼짐)
- IG_TOKEN_REFRESH_EVERY_DAYS : refresh 주기(일, 기본 40)
- IG_TOKEN_STORE_FILE         : 저장소 경로(기본 /app/logs/ig_tokens.json)
- IG_TOKEN_REFRESH_CHECK_HOUR : 매일 점검 시각(KST, 기본 5)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))
_REFRESH_URL = "https://graph.instagram.com/refresh_access_token"


def _truthy(key: str) -> bool:
    return (os.environ.get(key) or "").strip().lower() in ("1", "true", "yes", "on")


def _store_file() -> str:
    return (os.environ.get("IG_TOKEN_STORE_FILE") or "/app/logs/ig_tokens.json").strip()


def _every_days() -> int:
    try:
        return int((os.environ.get("IG_TOKEN_REFRESH_EVERY_DAYS") or "40").strip())
    except ValueError:
        return 40


def _check_hour() -> int:
    try:
        h = int((os.environ.get("IG_TOKEN_REFRESH_CHECK_HOUR") or "5").strip())
        return h if 0 <= h <= 23 else 5
    except ValueError:
        return 5


_STATE_KEY = "ig_tokens"


def load_store() -> dict:
    """{channel_id: {"token": str, "refreshed_at": iso, "expires_in": int}}

    저장 위치는 DB(`ops_state`). Cloud Run 파일시스템이 휘발성이라 파일에 두면
    갱신된 토큰이 사라지고 `.env` 의 낡은 토큰으로 되돌아간다. 상세: ops_state 모듈.
    """
    from app.admin.ops.services import ops_state

    return ops_state.load_json(_STATE_KEY, _store_file())


def _save_store(d: dict) -> None:
    from app.admin.ops.services import ops_state

    ops_state.save_json(_STATE_KEY, d, _store_file())


def current_token(cid: str) -> str:
    """채널 IG 토큰 — 저장소(refresh본) 우선, 없으면 env. `_ig_account`가 호출."""
    cid = (cid or "").strip()
    if not cid:
        return ""
    rec = load_store().get(cid)
    if rec and rec.get("token"):
        return str(rec["token"]).strip()
    return os.environ.get(f"CHANNEL_{cid}_IG_ACCESS_TOKEN", "").strip()


def _channels_with_token() -> list[str]:
    return sorted({
        m.group(1)
        for k in os.environ
        for m in [re.match(r"CHANNEL_(\d+)_IG_ACCESS_TOKEN$", k)]
        if m and os.environ.get(k, "").strip()
    })


async def refresh_all_due(*, force: bool = False) -> dict:
    """만료 임박(마지막 refresh가 EVERY_DAYS 이상 전) 또는 미기록 토큰을 refresh·저장.

    - 성공: 새 토큰 저장, refreshed_at=now
    - '24시간 이내 갱신불가'(방금 발급된 신선한 토큰): 현재 토큰을 now로 기록(다음 주기까지 대기)
    - '만료/무효': 저장 안 함 → needs_reissue 로 보고(사용자 재로그인 필요)
    """
    store = load_store()
    every = _every_days()
    now = datetime.now(_KST)
    refreshed, fresh, skipped, needs_reissue = [], [], [], []

    async with httpx.AsyncClient(timeout=20.0) as client:
        for cid in _channels_with_token():
            rec = store.get(cid)
            token = (rec or {}).get("token") or os.environ.get(f"CHANNEL_{cid}_IG_ACCESS_TOKEN", "").strip()
            if not token:
                continue
            if not force and rec and rec.get("refreshed_at"):
                try:
                    age = now - datetime.fromisoformat(rec["refreshed_at"])
                    if age < timedelta(days=every):
                        skipped.append(cid)
                        continue
                except ValueError:
                    pass
            try:
                r = await client.get(_REFRESH_URL, params={"grant_type": "ig_refresh_token", "access_token": token})
                data = r.json()
            except Exception as e:
                needs_reissue.append((cid, str(e)[:60]))
                continue
            newtok = data.get("access_token")
            if newtok:
                store[cid] = {"token": newtok, "refreshed_at": now.isoformat(), "expires_in": data.get("expires_in")}
                refreshed.append(cid)
                continue
            msg = str(data.get("error", {}).get("message", ""))
            if "24 hour" in msg or "24-hour" in msg or "24시간" in msg:
                # 방금 발급된 신선한 토큰 → 현재값을 now로 기록(다음 주기에 refresh)
                store[cid] = {"token": token, "refreshed_at": now.isoformat(), "expires_in": None}
                fresh.append(cid)
            else:
                needs_reissue.append((cid, msg[:60]))

    _save_store(store)
    logger.info(
        "ig_token_refresh done: refreshed=%s fresh=%s skipped=%d needs_reissue=%s",
        refreshed, fresh, len(skipped), [c for c, _ in needs_reissue],
    )
    return {"refreshed": refreshed, "fresh": fresh, "skipped": skipped, "needs_reissue": needs_reissue}


async def _loop() -> None:
    while True:
        now = datetime.now(_KST)
        nxt = now.replace(hour=_check_hour(), minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        await asyncio.sleep(max(1.0, (nxt - now).total_seconds()))
        try:
            await refresh_all_due()
        except Exception as e:
            logger.exception("ig_token_refresh loop failed: %s", e)


def loop_enabled() -> bool:
    """인프로세스 루프를 돌릴지. 미지정이면 IG_TOKEN_REFRESH_ENABLED 를 따른다.

    Cloud Run 은 min-instances=0 이면 상시 인스턴스가 없어 루프가 못 돈다.
    대신 Cloud Scheduler 가 run-now 엔드포인트를 호출한다 → 그 환경에선 IG_TOKEN_REFRESH_LOOP=0.
    """
    raw = (os.environ.get("IG_TOKEN_REFRESH_LOOP") or "").strip()
    return _truthy("IG_TOKEN_REFRESH_ENABLED") if raw == "" else raw.lower() in ("1", "true", "yes", "on")


def start() -> None:
    """앱 startup 에서 호출. env 로 켜졌을 때만 백그라운드 태스크 기동."""
    if not _truthy("IG_TOKEN_REFRESH_ENABLED"):
        logger.info("ig_token_refresh disabled (IG_TOKEN_REFRESH_ENABLED != 1)")
        return
    if not loop_enabled():
        logger.info("ig_token_refresh 인프로세스 루프 off (IG_TOKEN_REFRESH_LOOP=0) — Cloud Scheduler 가 호출")
        return
    try:
        asyncio.get_running_loop().create_task(_loop())
        logger.info("ig_token_refresh started (every=%dd, check_hour=%d KST)", _every_days(), _check_hour())
    except RuntimeError:
        logger.warning("ig_token_refresh: 러닝 루프 없음 — 기동 스킵")
