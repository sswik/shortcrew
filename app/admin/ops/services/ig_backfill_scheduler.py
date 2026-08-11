"""과거영상 → 인스타 백필 스케줄러 (shortcrew 내부, n8n 의존 0).

배경
----
13개 펌프채널의 **영상시트에 이미 완성(현지화완료)된 과거 쇼츠**가 채널당 70~128개
쌓여 있으나 인스타에는 안 올라가 있다. 이를 하루 소량씩(계정별 상한) IG 릴스로
백필한다. n8n 은 **일절 건드리지 않는다**(당일 신규영상 IG 발행은 기존 n8n 브랜치가
담당하고, 여기는 오직 오래된 미발행분만 집는다).

n8n 과 꼬이지 않는 이유
- n8n API/워크플로우/실행큐 접근 없음.
- 시트는 **다른 행·다른 열**만 만짐: n8n=오늘 행의 스테이지열 / 여기=2일 지난 행의 ig_media_id.
- IG 발행은 컨테이너 내부 `publish_reel_to_ig` 직접 호출(HTTP 엔드포인트 경합 없음).

중복 방지(airtight)
- `상태=현지화완료` AND `ig_media_id 비어있음` AND `drive_video_id 존재` 인 행만 대상.
- 오래된 순(No 오름차순)으로 집고, 발행 성공 시 응답 media_id 를 **ig_media_id 열에 되씀**.
- `업로드일시`가 MIN_AGE_HOURS 이내면 스킵 → 당일 신규발행분과 안 겹침.
- 컬럼 위치는 채널마다 다를 수 있어(예: tech 는 ig_media_id=S) **헤더명 기반**으로 해석.

env
---
- IG_BACKFILL_ENABLED       : "1"이면 켬(기본 꺼짐)
- IG_BACKFILL_CHANNELS      : 대상 채널 id 공백구분(기본 "09 10 11 13 14 15 23 24 25 33 34 37")
- IG_BACKFILL_SLOTS         : 실행 시각 HH:MM(KST) 공백구분(기본 "10:30 13:30 23:30")
- IG_BACKFILL_PER_ACCOUNT   : 계정당/일 상한(기본 2)
- IG_BACKFILL_WARMUP_DAYS   : 워밍업 일수(기본 5)
- IG_BACKFILL_WARMUP_PER_ACCOUNT : 워밍업 기간 계정당/일 상한(기본 1)
- IG_BACKFILL_START_DATE    : 워밍업 기준 시작일 YYYY-MM-DD(미설정 시 워밍업 무시=바로 정상캡)
- IG_BACKFILL_MIN_AGE_HOURS : 이 시간 안에 업로드된 영상은 제외(기본 48)
- IG_BACKFILL_VIDEO_TAB     : 영상시트 탭명(기본 "시트1")
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))
_SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"

# 헤더명 → 논리필드. 채널마다 열 위치가 달라도 이름으로 찾는다.
_H_STATUS = "상태"
_H_DRIVE = "drive_video_id"
_H_IGMEDIA = "ig_media_id"
_H_TITLE = "제목"
_H_DESC = "등록설명"
_H_UPLOADED = "업로드일시"
_DONE_STATUS = "현지화완료"

# 계정별 당일 발행 카운트를 파일에 지속화(마운트된 logs 볼륨) → 컨테이너 재시작에도 안전.
# {channel_id: {"date": "YYYY-MM-DD", "n": int}}
def _state_file() -> str:
    return (os.environ.get("IG_BACKFILL_STATE_FILE") or "/app/logs/ig_backfill_daily.json").strip()


def _load_daily() -> dict:
    try:
        with open(_state_file(), encoding="utf-8") as f:
            return json.load(f) or {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _save_daily(d: dict) -> None:
    try:
        path = _state_file()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except OSError as e:
        logger.warning("ig_backfill: 상태파일 저장 실패 %s", e)


def _truthy(key: str) -> bool:
    return (os.environ.get(key) or "").strip().lower() in ("1", "true", "yes", "on")


def _channels() -> list[str]:
    raw = os.environ.get("IG_BACKFILL_CHANNELS") or "09 10 11 13 14 15 23 24 25 33 34 37"
    return [c.strip() for c in raw.split() if c.strip()]


def _slots() -> list[tuple[int, int]]:
    raw = os.environ.get("IG_BACKFILL_SLOTS") or "10:30 13:30 23:30"
    out: list[tuple[int, int]] = []
    for tok in raw.split():
        try:
            hh, mm = tok.split(":")
            out.append((int(hh), int(mm)))
        except ValueError:
            continue
    return sorted(out) or [(10, 30), (13, 30), (23, 30)]


def _int_env(key: str, default: int) -> int:
    try:
        return int((os.environ.get(key) or str(default)).strip())
    except ValueError:
        return default


def _tab() -> str:
    return (os.environ.get("IG_BACKFILL_VIDEO_TAB") or "시트1").strip() or "시트1"


def _channel_tab(cid: str) -> str:
    """채널별 영상시트 탭. homecam(05)은 '아이디어' 등 구조가 달라 오버라이드 허용."""
    from app.admin.ops.channels.env_names import channel_env

    v = os.environ.get(channel_env(cid, "VIDEO_TAB"))
    return v.strip() if v and v.strip() else _tab()


def _done_status(cid: str) -> str:
    """채널별 '완성' 상태값. 기본 현지화완료, homecam(05)은 업로드완료 등."""
    from app.admin.ops.channels.env_names import channel_env

    v = os.environ.get(channel_env(cid, "DONE_STATUS"))
    if v and v.strip():
        return v.strip()
    return (os.environ.get("IG_BACKFILL_DONE_STATUS") or _DONE_STATUS).strip() or _DONE_STATUS


def effective_cap() -> int:
    """워밍업 기간이면 낮은 캡, 아니면 정상 캡."""
    full = _int_env("IG_BACKFILL_PER_ACCOUNT", 2)
    start = (os.environ.get("IG_BACKFILL_START_DATE") or "").strip()
    if not start:
        return full
    try:
        sd = datetime.strptime(start, "%Y-%m-%d").date()
    except ValueError:
        return full
    days = (datetime.now(_KST).date() - sd).days
    if days < _int_env("IG_BACKFILL_WARMUP_DAYS", 5):
        return _int_env("IG_BACKFILL_WARMUP_PER_ACCOUNT", 1)
    return full


def _today_str() -> str:
    return datetime.now(_KST).strftime("%Y-%m-%d")


def _posted_today(cid: str) -> int:
    rec = _load_daily().get(cid)
    if not rec or rec.get("date") != _today_str():
        return 0
    return int(rec.get("n") or 0)


def _bump_today(cid: str) -> None:
    today = _today_str()
    d = _load_daily()
    rec = d.get(cid)
    if not rec or rec.get("date") != today:
        d[cid] = {"date": today, "n": 1}
    else:
        rec["n"] = int(rec.get("n") or 0) + 1
    _save_daily(d)


def _col_letter(idx: int) -> str:
    """0-based 열 인덱스 → A1 표기(AA 이상 지원)."""
    s = ""
    n = idx
    while True:
        s = chr(65 + n % 26) + s
        n = n // 26 - 1
        if n < 0:
            break
    return s


# ── 구글 시트 IO (서비스계정) ────────────────────────────────────────────────
async def _token() -> str:
    from app.admin.ops.services.google_sheets import _get_access_token_from_keyfile

    return await asyncio.to_thread(_get_access_token_from_keyfile)


async def _read_grid(doc: str, tab: str) -> list[list[str]]:
    tok = await _token()
    rng = f"'{tab}'!A1:AZ4000" if (" " in tab) else f"{tab}!A1:AZ4000"
    async with httpx.AsyncClient(timeout=40.0) as c:
        r = await c.get(f"{_SHEETS_BASE}/{doc}/values/{rng}",
                        headers={"Authorization": f"Bearer {tok}"})
        if r.status_code >= 400:
            raise RuntimeError(f"sheet read {r.status_code}: {r.text[:200]}")
        return r.json().get("values", []) or []


async def _write_cell(doc: str, tab: str, a1: str, value: str) -> None:
    tok = await _token()
    cell = f"'{tab}'!{a1}" if (" " in tab) else f"{tab}!{a1}"
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.put(
            f"{_SHEETS_BASE}/{doc}/values/{cell}",
            params={"valueInputOption": "RAW"},
            json={"values": [[value]]},
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        )
        if r.status_code >= 400:
            raise RuntimeError(f"sheet write {r.status_code}: {r.text[:200]}")


# ── 채널 영상시트 docId 매핑 ─────────────────────────────────────────────────
def _video_sheet_id(cid: str) -> str | None:
    """채널의 영상시트 docId. env CHANNEL_{id}_VIDEO_SHEET_ID 우선, 없으면 로컬 n8n export 에서 추출."""
    from app.admin.ops.channels.env_names import channel_env  # 00식 CHANNEL_{ID}_{SUFFIX}

    for suffix in ("VIDEO_SHEET_ID", "VIDEO_FILE_ID", "SHEET_ID"):
        v = os.environ.get(channel_env(cid, suffix))
        if v and v.strip():
            return v.strip()
    return None


def _only_before() -> datetime | None:
    """이 날짜(YYYY-MM-DD) 이후 업로드분은 백필 제외 → 인라인 크로스포스트(신규발행)와 이중발행 방지.

    펌프 인라인 크로스포스트가 신규영상을 이미 IG에 올리지만 시트 ig_media_id 는 안 쓴다.
    백필이 그 신규분을 나중에 재발행하지 않도록, 크로스포스트 개시일 이후 업로드분은 건너뛴다.
    미설정이면 제한 없음(과거 백필 전용 채널 등).
    """
    raw = (os.environ.get("IG_BACKFILL_ONLY_BEFORE") or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=_KST)
    except ValueError:
        return None


def _parse_uploaded(val: str) -> datetime | None:
    val = (val or "").strip()
    if not val:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(val, fmt).replace(tzinfo=_KST)
        except ValueError:
            continue
    return None


async def _pick_pending(cid: str, doc: str, tab: str, min_age_h: int, done_status: str) -> dict | None:
    """오래된 순으로 백필 대상 1건 선택(없으면 None). 헤더명 기반 컬럼 해석.

    done_status: '완성' 상태값(채널별). 설명열은 등록설명/설명 중 있는 것 사용(homecam=설명).
    """
    grid = await _read_grid(doc, tab)
    if not grid:
        return None
    hdr = grid[0]

    def idx(name: str) -> int:
        return hdr.index(name) if name in hdr else -1

    i_st, i_dv, i_ig = idx(_H_STATUS), idx(_H_DRIVE), idx(_H_IGMEDIA)
    i_ti, i_up = idx(_H_TITLE), idx(_H_UPLOADED)
    i_de = next((idx(n) for n in ("등록설명", "설명") if idx(n) >= 0), -1)  # 채널별 설명열
    if min(i_st, i_dv, i_ig) < 0:
        logger.warning("ig_backfill: %s 헤더결측 상태=%s drive=%s ig=%s", cid, i_st, i_dv, i_ig)
        return None

    now = datetime.now(_KST)
    only_before = _only_before()
    for r, row in enumerate(grid[1:], start=2):  # 시트 실제 행번호(헤더=1)
        def cell(i: int) -> str:
            return row[i].strip() if 0 <= i < len(row) and row[i] is not None else ""

        if cell(i_st) != done_status:
            continue
        if not cell(i_dv):
            continue
        if cell(i_ig):  # 이미 IG 발행됨
            continue
        up = _parse_uploaded(cell(i_up)) if i_up >= 0 else None
        if up and (now - up) < timedelta(hours=min_age_h):
            continue  # 너무 최근 영상 → 당일 신규분과 충돌 방지
        if only_before and up and up >= only_before:
            continue  # 인라인 크로스포스트가 처리하는 신규분 → 백필 제외(이중발행 방지)
        title = cell(i_ti) if i_ti >= 0 else ""
        desc = cell(i_de) if i_de >= 0 else ""
        caption = (title + "\n\n" + desc).strip()[:2100]
        return {
            "row": r,
            "drive_id": cell(i_dv),
            "caption": caption,
            "ig_col": _col_letter(i_ig),
        }
    return None


async def _publish_one(cid: str, cap: int, min_age: int, dry_run: bool) -> tuple[str, str]:
    """채널 1건 처리. ('published'|'skipped'|'error', 상세) 반환(예외 안 냄)."""
    from app.admin.ops.services.youtube_ig_bridge import publish_reel_to_ig

    if _posted_today(cid) >= cap:
        return "skipped", "cap"
    doc = _video_sheet_id(cid)
    if not doc:
        return "skipped", "no-sheet-id"
    try:
        pick = await _pick_pending(cid, doc, _channel_tab(cid), min_age, _done_status(cid))
    except Exception as e:
        return "error", f"pick:{str(e)[:80]}"
    if not pick:
        return "skipped", "no-pending"
    vurl = f"https://drive.google.com/uc?export=download&id={pick['drive_id']}"
    try:
        res = await publish_reel_to_ig(
            channel_id=cid, video_url=vurl, caption=pick["caption"],
            share_to_feed=True, dry_run=dry_run,
        )
        if dry_run:
            return "published", f"DRY row{pick['row']} {pick['drive_id'][:12]}"
        mid = str(res.get("media_id") or "").strip()
        if not mid:
            return "error", "no-media-id"
    except Exception as e:
        return "error", str(e)[:100]

    # 여기부터는 IG 발행이 이미 끝난 상태 — 실패해도 'error'로 두면 재시도가 같은 영상을
    # 두 번 올린다. 시트 기록 실패는 published 로 반환하고 경고만 남긴다(수동 보정 대상).
    try:
        # ig_media_id 되씀 → 영구 중복차단
        await _write_cell(doc, _channel_tab(cid), f"{pick['ig_col']}{pick['row']}", mid)
    except Exception as e:
        _bump_today(cid)
        logger.warning("ig_backfill %s: 발행됐으나 시트기록 실패 row=%s media=%s (%s) — "
                       "%s%s 에 수동 기록 필요", cid, pick["row"], mid, str(e)[:80],
                       pick["ig_col"], pick["row"])
        return "published", f"row{pick['row']} media={mid} SHEET-WRITE-FAILED"
    _bump_today(cid)
    return "published", f"row{pick['row']} media={mid}"


async def run_backfill_once(*, dry_run: bool = False) -> dict:
    """모든 슬롯 공통 1패스: 대상 채널을 돌며 계정별 상한 안에서 1건씩 발행.

    실패 채널은 패스 끝에서 1회 재시도한다(IG 인코딩/Drive 전송 일시장애가 잦고,
    23:30 은 그날 마지막 슬롯이라 재시도가 없으면 하루치가 통째로 밀린다).
    """
    cap = effective_cap()
    min_age = _int_env("IG_BACKFILL_MIN_AGE_HOURS", 48)

    published, skipped, errors = [], [], []
    for cid in _channels():
        kind, detail = await _publish_one(cid, cap, min_age, dry_run)
        {"published": published, "skipped": skipped, "errors": errors}[kind].append((cid, detail))

    # 실패분 1회 재시도 — 대개 여기서 붙는다.
    if errors and not dry_run:
        retry, errors = errors, []
        logger.warning("ig_backfill 실패 %d채널 재시도: %s", len(retry), [c for c, _ in retry])
        await asyncio.sleep(_int_env("IG_BACKFILL_RETRY_WAIT_S", 30))
        for cid, first_err in retry:
            kind, detail = await _publish_one(cid, cap, min_age, dry_run)
            if kind == "published":
                published.append((cid, f"retry {detail}"))
            elif kind == "skipped":
                skipped.append((cid, f"retry {detail}"))
            else:
                errors.append((cid, f"{first_err} | retry:{detail}"))

    log = logger.warning if errors else logger.info
    log("ig_backfill pass done cap=%s pub=%d skip=%d err=%d%s", cap, len(published),
        len(skipped), len(errors), (" " + repr(errors)) if errors else "")
    return {"cap": cap, "dry_run": dry_run, "published": published,
            "skipped": skipped, "errors": errors}


async def _loop() -> None:
    slots = _slots()
    while True:
        now = datetime.now(_KST)
        # 다음 슬롯 계산
        cands = []
        for hh, mm in slots:
            t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if t <= now:
                t += timedelta(days=1)
            cands.append(t)
        nxt = min(cands)
        await asyncio.sleep(max(1.0, (nxt - now).total_seconds()))
        try:
            await run_backfill_once()
        except Exception as e:  # 실패해도 루프·앱 유지
            logger.exception("ig_backfill loop failed: %s", e)


def start() -> None:
    """앱 startup 에서 호출. env 로 켜졌을 때만 백그라운드 태스크 기동."""
    if not _truthy("IG_BACKFILL_ENABLED"):
        logger.info("ig_backfill disabled (IG_BACKFILL_ENABLED != 1)")
        return
    try:
        asyncio.get_running_loop().create_task(_loop())
        logger.info(
            "ig_backfill started (channels=%d, slots=%s, cap=%s, warmup_until_start=%s)",
            len(_channels()), _slots(), effective_cap(),
            os.environ.get("IG_BACKFILL_START_DATE") or "-",
        )
    except RuntimeError:
        logger.warning("ig_backfill: 러닝 루프 없음 — 기동 스킵")
