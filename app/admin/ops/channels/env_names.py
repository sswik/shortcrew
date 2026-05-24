"""채널별 `.env` 키 이름 규칙: `CHANNEL_{CHANNEL_ID}_SUFFIX` (CHANNEL_ID는 대문자·하이픈→밑줄)."""

from __future__ import annotations


def channel_env(channel_id: str, suffix: str) -> str:
    """예: `channel_env(\"201\", \"FILE_ID\")` → `CHANNEL_201_FILE_ID`."""
    cid = channel_id.strip().replace("-", "_").upper()
    suf = suffix.strip().upper().replace("-", "_")
    return f"CHANNEL_{cid}_{suf}"
