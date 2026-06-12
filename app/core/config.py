"""환경 변수 로딩·사이트 URL 정규화·공통 상수. (앱/모델 비의존 leaf 모듈)"""
from __future__ import annotations

import os
from datetime import timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

# 한국 표준시(KST)
KST = timezone(timedelta(hours=9))


def load_env() -> None:
    """`.env` 를 읽어, **현재 값이 비어 있을 때만** 키를 채운다.
    (셸에 빈 CHANNEL_* 만 export 되어 있어 .env 가 무시되는 문제 방지)
    다른 모듈이 os.environ 을 읽기 전에 호출해야 한다."""
    path = _ROOT / ".env"
    if not path.is_file():
        return
    from dotenv import dotenv_values

    for key, val in dotenv_values(path).items():
        if val is None:
            continue
        cur = os.environ.get(key)
        if cur is None or cur.strip() == "":
            os.environ[key] = val


def normalize_site_base(url: str) -> str:
    """`PUBLIC_SITE_URL` 등 — 스킴 없는 호스트·`//` 형태를 절대 URL로."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if not url.startswith(("http://", "https://")):
        return "https://" + url.lstrip("/")
    return url
