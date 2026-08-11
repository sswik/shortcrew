"""Gemini 모델명 단일 소스.

모델을 각 서비스에 하드코딩하면 은퇴(2.5-flash 종료 등) 때마다 여러 파일을 훑어야 한다.
여기 한 곳에서 읽고, 교체는 `.env` 의 `GEMINI_MODEL` 한 줄로 끝낸다.

주의: 모델명은 `models.list` 에 있는 정확한 id 여야 한다(`gemini-3-flash` 같은 id 는 없음).
확인: curl "https://generativelanguage.googleapis.com/v1beta/models?key=$GOOGLE_GEMINI_KEY"
"""
from __future__ import annotations

import os

# 2026-08 기준 정식판. 짧은 한국어 생성 + 구조화 출력 용도라 lite 로 충분하고,
# 2.5-flash 보다 저렴하다($0.25/$1.50 vs $0.30/$2.50).
DEFAULT_MODEL = "gemini-3.1-flash-lite"


def gemini_model() -> str:
    """사용할 Gemini 모델명. env `GEMINI_MODEL` 이 있으면 그것, 없으면 기본값."""
    return (os.environ.get("GEMINI_MODEL") or "").strip() or DEFAULT_MODEL
