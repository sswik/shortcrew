"""시트 상품명 매칭용 정규화 (엄격 → 느슨 2단계)."""

from __future__ import annotations

import re
import unicodedata


def normalize_match_key_strict(name: str) -> str:
    """공백 제거·NFKC·소문자(영문)·특수문자 다량 제거."""
    s = unicodedata.normalize("NFKC", (name or "").strip().lower())
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^\w가-힣0-9]", "", s, flags=re.UNICODE)
    return s


def normalize_match_key_loose(name: str) -> str:
    """한글·숫자·영문만 남김 (괄호·단위 등 제거)."""
    s = unicodedata.normalize("NFKC", (name or "").strip().lower())
    s = re.sub(r"[^0-9a-z가-힣]", "", s)
    return s


def names_equivalent(a: str, b: str) -> bool:
    if normalize_match_key_strict(a) == normalize_match_key_strict(b) and normalize_match_key_strict(a):
        return True
    la = normalize_match_key_loose(a)
    lb = normalize_match_key_loose(b)
    return bool(la) and la == lb
