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
    다른 모듈이 os.environ 을 읽기 전에 호출해야 한다.

    경로는 기본 `<프로젝트루트>/.env` 이며, env `ENV_FILE` 로 덮어쓸 수 있다.
    Cloud Run 에서는 Secret Manager 시크릿을 `/secrets/env` 로 마운트하고
    `ENV_FILE=/secrets/env` 를 준다(`/app/.env` 에 직접 마운트하면 코드 디렉터리가 가려진다)."""
    override = (os.environ.get("ENV_FILE") or "").strip()
    path = Path(override) if override else _ROOT / ".env"
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
