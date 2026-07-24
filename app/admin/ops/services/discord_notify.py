"""앱-사이드 디스코드 알림 (n8n 없이 앱이 직접 웹훅 전송).

내부 스케줄러(큐레이션·후기대본 브리지 등)의 성공요약/실패경보용.
알림 자체가 스케줄러를 죽이면 안 되므로, 전송 실패는 로그만 남기고 삼킨다.
env: DISCORD_WEBHOOK (없으면 조용히 skip).
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)


async def notify(content: str, *, env_key: str = "DISCORD_WEBHOOK") -> bool:
    """디스코드로 한 줄 알림 전송. 성공 True. URL 미설정/실패 시 False(예외 안 냄).

    env_key: 웹훅 URL 을 읽을 환경변수명. 채널을 분리하려면 다른 키 지정
    (예: 인스타 업로드완료 알림은 env_key="DISCORD_WEBHOOK_IG").
    """
    url = (os.environ.get(env_key) or "").strip()
    if not url:
        logger.info("discord_notify skip (%s 미설정): %s", env_key, content[:80])
        return False
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={"content": content[:1900]}, timeout=15.0)
            resp.raise_for_status()
        return True
    except Exception as e:  # 알림 실패가 스케줄러를 죽이면 안 됨 — 로그만
        logger.warning("discord_notify failed: %s", e)
        return False
