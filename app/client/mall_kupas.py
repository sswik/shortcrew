"""쿠파스 채널 몰: 시트 A~Q 직접 읽기 + «영상 속 번호 상품» 구역.

쿠파스 쇼츠는 영상 끝에서 「프로필 링크 N번」이라고 말한다. 그래서 이 채널들의 몰은
번호를 **시트 A열(No) 그대로** 써야 한다(시트 순서 번호로는 빈 번호·중복을 못 맞춘다).

대상 채널은 env `MALL_KUPAS_CHANNELS`(쉼표·공백 구분). 키가 없으면 기본 5개 채널,
빈 값이면 기능 전체 꺼짐(= 기존 Apps Script 경로로 복귀).

시트 상품탭 열(기존 A~K + 쿠파스 L~Q)
  A No · B 카테고리 · C 상품명 · D 가격 · E 이미지 · F 쿠팡URL · G 딥링크 · H 연관영상
  I 게시상태 · J 등록일 · K subId · L 평점 · M 상품평수 · N 특징(· 구분) · O 수집일
  P 공개시각(ISO UTC, 이 시각 전엔 비노출) · Q 구분(`쿠파스` 면 위 구역)

응답(JSON 배열)
- 쿠파스 행(Q=쿠파스, I=게시중, 공개시각 경과): `section="kupas"` + `no`·`rating`·`reviewCount`
  ·`features`·`publishAt`·`video`(H열이 유튜브 ID 일 때). 번호 큰 것(최신 영상)부터.
- 그 밖의 행: Apps Script 응답과 **동일한 형태·순서·범위**(`name/price/image/deepLink/category`,
  상품명이 있는 모든 행, 게시상태 무관). 2026-10-09 5개 채널 전수 대조로 일치 확인 — 기존 번호
  (시트 순서)가 바뀌지 않게 하기 위함이다.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

KUPAS_SECTION = "쿠파스"
KUPAS_COLUMNS = ("평점", "상품평수", "특징", "수집일", "공개시각", "구분")  # L~Q 헤더
_DEFAULT_CHANNELS = "02,03,15,31,35"
_FEATURE_SPLIT = re.compile(r"\s*[·|]\s*")
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")  # H열이 유튜브 영상 ID 일 때만 «영상 보기» 링크


def kupas_channels() -> set[str]:
    raw = os.environ.get("MALL_KUPAS_CHANNELS")
    if raw is None:
        raw = _DEFAULT_CHANNELS
    return {c for c in re.split(r"[\s,]+", raw.strip()) if c}


def is_kupas_channel(channel_id: str) -> bool:
    return (channel_id or "").strip() in kupas_channels()


def quoted_range(tab: str, a1: str) -> str:
    """탭 이름을 항상 작은따옴표로 감싼 A1 범위(한글·하이픈 탭 안전)."""
    return "'" + tab.replace("'", "''") + "'!" + a1


def _cell(row: list, idx: int) -> str:
    return str(row[idx]).strip() if idx < len(row) and row[idx] is not None else ""


def _int_or_none(s: str) -> int | None:
    digits = re.sub(r"[^\d]", "", s or "")
    return int(digits) if digits else None


def _float_or_none(s: str) -> float | None:
    try:
        return float((s or "").replace(",", "").strip())
    except ValueError:
        return None


def parse_publish_at(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_no(s: str) -> int | None:
    s = (s or "").strip()
    return int(s) if s.isdigit() else None


def is_kupas_row(row: list) -> bool:
    return _cell(row, 16) == KUPAS_SECTION


def build_items(rows: list[list], now: datetime | None = None) -> list[dict]:
    """시트 A2:Q 행 → 몰 응답 배열(쿠파스 구역 먼저, 기존 상품은 시트 순서 그대로)."""
    now = now or datetime.now(timezone.utc)
    kupas: dict[int, dict] = {}
    legacy: list[dict] = []
    for row in rows:
        name = _cell(row, 2)
        if not name:
            continue
        if not is_kupas_row(row):
            price_raw = _cell(row, 3)
            price_digits = re.sub(r"[^\d]", "", price_raw)
            legacy.append({
                "name": name,
                "price": int(price_digits) if price_digits and price_digits == price_raw.replace(",", "") else price_raw,
                "image": _cell(row, 4),
                "deepLink": _cell(row, 6),
                "category": _cell(row, 1),
            })
            continue
        no = parse_no(_cell(row, 0))
        if no is None or _cell(row, 8) != "게시중":
            continue
        pub_raw = _cell(row, 15)
        if pub_raw:
            pub = parse_publish_at(pub_raw)
            if pub is None or pub > now:  # 형식 오류도 비노출(영상 공개 전 노출 방지 우선)
                continue
        feats = [f for f in _FEATURE_SPLIT.split(_cell(row, 13)) if f][:4]
        kupas[no] = {  # 같은 번호가 두 줄이면 아래 줄(나중 기록)이 이김
            "section": "kupas",
            "no": no,
            "name": name,
            "image": _cell(row, 4),
            "deepLink": _cell(row, 6) or _cell(row, 5),
            "category": _cell(row, 1),
            "rating": _float_or_none(_cell(row, 11)),
            "reviewCount": _int_or_none(_cell(row, 12)),
            "features": feats,
            "publishAt": pub_raw,
            "video": _cell(row, 7) if _YOUTUBE_ID.match(_cell(row, 7)) else "",
        }
    ordered = [kupas[k] for k in sorted(kupas, reverse=True)]
    return ordered + legacy
