"""YouTube 자막·메타: yt-dlp 우선, Data API snippet 폴백."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import httpx

logger = logging.getLogger(__name__)


def _strip_vtt_to_text(raw: str) -> str:
    lines = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or line.startswith("WEBVTT") or line.startswith("NOTE") or "-->" in line:
            continue
        line = re.sub(r"<\/?[^>]+>", "", line)
        if line.isdigit():
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _pick_sub_url_from_dump(data: dict) -> str | None:
    """dump-json automatic_captions / subtitles 에서 ko → en 순."""
    for key in ("automatic_captions", "subtitles"):
        block = data.get(key) or {}
        if not isinstance(block, dict):
            continue
        for lang in (
            "ko",
            "ko-KR",
            "ko_kr",
            "en",
            "en-US",
            "en-GB",
        ):
            tracks = block.get(lang) or block.get(lang.replace("_", "-"))
            if not isinstance(tracks, list):
                continue
            for tr in tracks:
                if not isinstance(tr, dict):
                    continue
                url = (tr.get("url") or "").strip()
                ext = (tr.get("ext") or "").lower()
                if url and ext in ("json3", "srv1", "srv2", "srv3", "vtt", "ttml"):
                    return url
                if url:
                    return url
    return None


def fetch_transcript_via_ytdlp_dump(url: str, *, timeout: int = 90) -> str | None:
    """yt-dlp --dump-json 으로 자막 URL 후보를 찾아 텍스트 추출."""
    cmd = [
        "yt-dlp",
        "-q",
        "--no-warnings",
        "--dump-json",
        "--skip-download",
        url,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        logger.warning("yt-dlp not found in PATH")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("yt-dlp dump-json timeout url=%s", url[:80])
        return None
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    sub_url = _pick_sub_url_from_dump(data)
    if not sub_url:
        return None
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(sub_url)
            r.raise_for_status()
    except Exception:
        logger.exception("subtitle fetch failed")
        return None
    text = _strip_vtt_to_text(r.text)
    return text or None


async def fetch_snippet_via_data_api(video_id: str, api_key: str) -> tuple[str, str]:
    """(title, description) — 키 없으면 빈 문자열."""
    key = (api_key or "").strip()
    if not key or not video_id:
        return "", ""
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {"part": "snippet", "id": video_id, "key": key}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("youtube data api videos.list failed")
        return "", ""
    items = data.get("items") or []
    if not items or not isinstance(items[0], dict):
        return "", ""
    snip = items[0].get("snippet") or {}
    title = (snip.get("title") or "").strip()
    desc = (snip.get("description") or "").strip()
    return title, desc


def build_fallback_text(title: str, description: str) -> str:
    parts = []
    if title:
        parts.append(f"제목: {title}")
    if description:
        parts.append(f"설명:\n{description}")
    return "\n\n".join(parts).strip()


async def resolve_transcript_text(
    youtube_url: str,
    video_id: str,
    *,
    youtube_api_key: str,
) -> str:
    """자막 우선, 실패 시 제목+설명."""
    from asyncio import to_thread

    dumped = await to_thread(fetch_transcript_via_ytdlp_dump, youtube_url)
    if dumped and len(dumped) > 40:
        return dumped
    title, desc = await fetch_snippet_via_data_api(video_id, youtube_api_key)
    fb = build_fallback_text(title, desc)
    if fb:
        return fb
    return dumped or ""
