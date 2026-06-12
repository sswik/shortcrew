"""Jinja2 템플릿 엔진(클라이언트+어드민 디렉터리). 앱 비의존 — 예외 핸들러·라우트가 공유한다."""
from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

_ROOT = Path(__file__).resolve().parents[2]

templates = Jinja2Templates(
    directory=[
        str(_ROOT / "app" / "client" / "templates"),
        str(_ROOT / "app" / "admin" / "templates"),
    ]
)
