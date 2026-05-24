"""ops 라우트 공통: env, 채널 설정 JSON, URL 로깅 헬퍼, mall 클릭 JSONL."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Request

from app.admin.ops._paths import project_root
from app.admin.ops.auth import get_request_env


def url_kind(url: str) -> str:
    value = (url or "").strip().lower()
    if not value:
        return "empty"
    if "link.coupang.com/" in value:
        return "short"
    if "coupang.com/vp/" in value:
        return "vp"
    return "other"


def count_url_kinds(urls: list[str]) -> dict[str, int]:
    counts = {"short": 0, "vp": 0, "other": 0, "empty": 0}
    for url in urls:
        counts[url_kind(url)] += 1
    return counts


def sample_urls(urls: list[str], limit: int = 3) -> list[str]:
    return [u[:200] for u in urls[: max(0, limit)]]


def channel_settings_path() -> Path:
    data_dir = project_root() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "channel_settings.json"


def load_channel_settings() -> dict:
    path = channel_settings_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_channel_settings(data: dict) -> None:
    path = channel_settings_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_channel_by_alias(alias: str) -> dict | None:
    value = (alias or "").strip()
    if not value:
        return None
    from app.admin.ops.channels import get_channels

    for channel in get_channels():
        channel_id = str(channel.get("channel_id") or "").strip()
        channel_name = str(channel.get("name") or "").strip()
        if value and (value == channel_id or value == channel_name):
            return channel
    return None


def resolve_channel_aliases(channel_filter: str) -> set[str]:
    value = (channel_filter or "").strip()
    if not value:
        return set()
    aliases = {value}
    matched = find_channel_by_alias(value)
    if matched:
        channel_id = str(matched.get("channel_id") or "").strip()
        channel_name = str(matched.get("name") or "").strip()
        if channel_id:
            aliases.add(channel_id)
        if channel_name:
            aliases.add(channel_name)
    return aliases


def filter_mall_click_logs_by_channel(logs: list[dict], channel_filter: str) -> list[dict]:
    aliases = resolve_channel_aliases(channel_filter)
    if not aliases:
        return logs
    filtered: list[dict] = []
    for row in logs:
        candidates = {
            str(row.get("channel") or "").strip(),
            str(row.get("channel_id") or "").strip(),
            str(row.get("channel_name") or "").strip(),
        }
        if any(candidate and candidate in aliases for candidate in candidates):
            filtered.append(row)
    return filtered


def mall_click_logs_dir() -> Path:
    data_dir = project_root() / "data" / "mall_click_logs"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def mall_click_log_file_for_date(date_str: str) -> Path:
    return mall_click_logs_dir() / f"{date_str}.jsonl"


def append_jsonl_line(path: Path, payload: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


async def append_mall_click_record(payload: dict) -> None:
    date_key = str(payload.get("eventDate") or "").strip()
    if not date_key:
        date_key = datetime.now(timezone.utc).date().isoformat()
    log_path = mall_click_log_file_for_date(date_key)
    await asyncio.to_thread(append_jsonl_line, log_path, payload)


def read_jsonl_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except Exception:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


async def load_recent_mall_click_records(days: int = 7) -> list[dict]:
    days = max(1, min(int(days or 7), 31))
    today = datetime.now(timezone.utc).date()
    paths = [
        mall_click_log_file_for_date((today - timedelta(days=delta)).isoformat())
        for delta in range(days)
    ]
    nested = await asyncio.gather(*[
        asyncio.to_thread(read_jsonl_records, path) for path in paths
    ])
    merged: list[dict] = []
    for group in nested:
        merged.extend(group)
    return merged


def get_env_secret(request: Request, key: str) -> str:
    env = get_request_env(request)
    if env is not None and hasattr(env, "get"):
        return (env.get(key) or "") or ""
    return os.environ.get(key, "")
