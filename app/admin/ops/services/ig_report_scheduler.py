"""인스타그램 일일 운영 리포트 → 디스코드 (shortcrew 내부, n8n 무관).

운영 상세는 `06.운영가이드/15_인스타_일일운영리포트.md` 참고.

배경
----
유튜브 쪽은 n8n `WF-OPS 일일 운영 리포트`가 워크플로우 실행 성공/실패를 디스코드로 쏜다.
인스타는 그런 리포트가 없었다. 다만 **갱신된 IG 토큰은 앱의 토큰 저장소에만 있으므로**
(`ig_token_refresh`), n8n 이 아니라 앱 내부 스케줄러가 리포트를 만든다. n8n 에 토큰을
박으면 60일 뒤 또 만료로 죽는다.

리포트 내용
-----------
1) 성과: 채널별 팔로워(전일 대비 증감) / 24h 조회수·도달·상호작용 / 24h 발행 릴스 수
2) 발행 파이프라인: 24h 발행 0건 채널, 인사이트 조회 실패 채널, 토큰 만료 임박(D-일)
3) 상위 릴스: 24h 내 발행분 중 조회수 상위 N개 링크

데이터 출처는 Graph API(graph.instagram.com) 뿐이라 크로스포스트(n8n)든 백필(앱)이든
경로와 무관하게 "실제로 인스타에 올라간 것"만 집계된다.

env
---
- IG_REPORT_ENABLED     : "1"이면 켬(기본 꺼짐)
- IG_REPORT_AT          : 발송 시각 HH:MM(KST, 기본 "20:30")
- IG_REPORT_CHANNELS    : 대상 채널 id 공백구분(기본 = 토큰 보유 전 채널)
- IG_REPORT_WEBHOOK_ENV : 디스코드 웹훅 env 키(기본 DISCORD_WEBHOOK_IG)
- IG_REPORT_TOP_N       : 상위 릴스 표시 개수(기본 3)
- IG_REPORT_STATE_FILE  : 팔로워 스냅샷 파일(기본 /app/logs/ig_report_state.json)
- IG_GRAPH_VERSION      : Graph API 버전(기본 v23.0)
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
_TOKEN_TTL_SEC = 60 * 24 * 3600  # IG 장기토큰 60일


def _truthy(key: str) -> bool:
    return (os.environ.get(key) or "").strip().lower() in ("1", "true", "yes", "on")


def _int_env(key: str, default: int) -> int:
    try:
        return int((os.environ.get(key) or str(default)).strip())
    except ValueError:
        return default


def _graph_base() -> str:
    ver = (os.environ.get("IG_GRAPH_VERSION") or "v23.0").strip() or "v23.0"
    return f"https://graph.instagram.com/{ver}"


def _at() -> tuple[int, int]:
    raw = (os.environ.get("IG_REPORT_AT") or "20:30").strip()
    try:
        hh, mm = raw.split(":")
        h, m = int(hh), int(mm)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except ValueError:
        pass
    return 20, 30


def _state_file() -> str:
    return (os.environ.get("IG_REPORT_STATE_FILE") or "/app/logs/ig_report_state.json").strip()


def _load_state() -> dict:
    try:
        with open(_state_file(), encoding="utf-8") as f:
            return json.load(f) or {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _save_state(d: dict) -> None:
    try:
        path = _state_file()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except OSError as e:
        logger.warning("ig_report: 상태파일 저장 실패 %s", e)


def report_channels() -> list[str]:
    """대상 채널. env 미지정 시 IG 계정 ID + 유효 토큰이 있는 전 채널."""
    raw = (os.environ.get("IG_REPORT_CHANNELS") or "").strip()
    if raw:
        return [c.strip() for c in raw.replace(",", " ").split() if c.strip()]

    from app.admin.ops.channels.env_names import channel_env

    out: list[str] = []
    for key in os.environ:
        if not key.startswith("CHANNEL_") or not key.endswith("_IG_ACCOUNT_ID"):
            continue
        cid = key[len("CHANNEL_"):-len("_IG_ACCOUNT_ID")]
        if not os.environ.get(channel_env(cid, "IG_ACCOUNT_ID"), "").strip():
            continue
        out.append(cid)
    return sorted(set(out))


def _channel_name(cid: str) -> str:
    """표시명. 로스터 → env `CHANNEL_{id}_NAME` → IG username → id 순 폴백.

    로스터(`channels/roster`)에 없는 채널도 IG 계정만 있으면 리포트에 잡히므로
    (예: 100 에이전트PM) id 만 찍히지 않게 폴백을 둔다.
    """
    from app.admin.ops.channels import get_channels
    from app.admin.ops.channels.env_names import channel_env

    for ch in get_channels():
        if str(ch.get("channel_id") or "").strip() == cid:
            return str(ch.get("name") or cid)
    for key in ("NAME", "IG_USERNAME"):
        v = os.environ.get(channel_env(cid, key), "").strip()
        if v:
            return v
    return cid


def _account(cid: str) -> tuple[str, str]:
    """(account_id, token). 토큰은 자동갱신 저장소 우선(= dm.py `_ig_account` 와 동일 규칙)."""
    from app.admin.ops.channels.env_names import channel_env
    from app.admin.ops.services.ig_token_refresh import current_token

    return (
        os.environ.get(channel_env(cid, "IG_ACCOUNT_ID"), "").strip(),
        current_token(cid),
    )


def _token_days_left(cid: str) -> int | None:
    """토큰 저장소 기준 남은 만료일. 저장소에 없으면 None(= env 원본, 만료일 모름)."""
    try:
        from app.admin.ops.services.ig_token_refresh import load_store

        rec = (load_store() or {}).get(cid) or {}
    except Exception:
        return None
    ts = str(rec.get("refreshed_at") or "").strip()
    if not ts:
        return None
    try:
        refreshed = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if refreshed.tzinfo is None:
        refreshed = refreshed.replace(tzinfo=timezone.utc)
    try:
        ttl = int(rec.get("expires_in") or _TOKEN_TTL_SEC)
    except (TypeError, ValueError):
        ttl = _TOKEN_TTL_SEC
    left = (refreshed + timedelta(seconds=ttl)) - datetime.now(timezone.utc)
    return int(left.total_seconds() // 86400)


async def _get(client: httpx.AsyncClient, path: str, token: str, **params) -> dict:
    params["access_token"] = token
    resp = await client.get(f"{_graph_base()}/{path}", params=params, timeout=25.0)
    resp.raise_for_status()
    return resp.json() or {}


def _insight_values(payload: dict) -> dict[str, int]:
    """account insights(metric_type=total_value) → {metric: value}."""
    out: dict[str, int] = {}
    for item in payload.get("data") or []:
        name = str(item.get("name") or "")
        val = (item.get("total_value") or {}).get("value")
        if val is None:
            vals = item.get("values") or []
            val = (vals[0] or {}).get("value") if vals else None
        if name and val is not None:
            try:
                out[name] = int(val)
            except (TypeError, ValueError):
                continue
    return out


def _media_views(payload: dict) -> int:
    for item in payload.get("data") or []:
        if str(item.get("name")) != "views":
            continue
        vals = item.get("values") or []
        try:
            return int((vals[0] or {}).get("value") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


async def _collect_channel(client: httpx.AsyncClient, cid: str, since: datetime) -> dict:
    """채널 1개 수집. 실패는 예외 대신 error 필드로 담아 리포트 전체를 살린다."""
    acct, token = _account(cid)
    row: dict = {"cid": cid, "name": _channel_name(cid), "days_left": _token_days_left(cid)}
    if not acct or not token:
        row["error"] = "계정/토큰 없음"
        return row

    try:
        me = await _get(client, acct, token, fields="username,followers_count,media_count")
        row["username"] = str(me.get("username") or "")
        row["followers"] = int(me.get("followers_count") or 0)
    except Exception as e:
        row["error"] = f"계정조회 {str(e)[:60]}"
        return row

    try:
        ins = await _get(
            client, f"{acct}/insights", token,
            metric="views,reach,total_interactions", period="day", metric_type="total_value",
        )
        row.update(_insight_values(ins))
    except Exception as e:
        row["insight_error"] = str(e)[:60]

    try:
        media = await _get(
            client, f"{acct}/media", token,
            fields="id,timestamp,permalink,media_product_type,like_count,comments_count",
            limit=25,
        )
    except Exception as e:
        row["media_error"] = str(e)[:60]
        return row

    fresh = []
    for m in media.get("data") or []:
        ts = str(m.get("timestamp") or "")
        try:
            when = datetime.fromisoformat(ts.replace("+0000", "+00:00"))
        except ValueError:
            continue
        if when >= since:
            fresh.append({**m, "when": when})
    row["posted"] = len(fresh)

    for m in fresh:
        try:
            mi = await _get(client, f"{m['id']}/insights", token, metric="views")
            m["views"] = _media_views(mi)
        except Exception:
            m["views"] = 0
    row["reels"] = sorted(fresh, key=lambda x: x.get("views") or 0, reverse=True)
    return row


def _build_message(rows: list[dict], since: datetime, now: datetime, prev: dict) -> str:
    nl = "\n"
    pad = lambda n: str(n).zfill(2)  # noqa: E731
    span = (
        f"{pad(since.month)}/{pad(since.day)} {pad(since.hour)}:{pad(since.minute)}"
        f" ~ {pad(now.month)}/{pad(now.day)} {pad(now.hour)}:{pad(now.minute)}"
    )

    ok = [r for r in rows if not r.get("error")]
    tot_followers = sum(r.get("followers") or 0 for r in ok)
    tot_views = sum(r.get("views") or 0 for r in ok)
    tot_reach = sum(r.get("reach") or 0 for r in ok)
    tot_inter = sum(r.get("total_interactions") or 0 for r in ok)
    tot_posted = sum(r.get("posted") or 0 for r in ok)

    delta_total = 0
    has_baseline = False
    for r in ok:
        before = (prev.get(r["cid"]) or {}).get("followers")
        if isinstance(before, int):
            r["delta"] = (r.get("followers") or 0) - before
            delta_total += r["delta"]
            has_baseline = True
    # 첫 실행은 전일 스냅샷이 없다 — 0 증가로 오해되지 않게 증감 표기를 생략.
    delta_str = f"({delta_total:+d})" if has_baseline else ""

    head = f"**인스타 일일 운영 리포트** ({span}){nl}"
    head += (
        f"전체: 팔로워 **{tot_followers}**{delta_str} / 조회 **{tot_views}** / "
        f"도달 **{tot_reach}** / 상호작용 **{tot_inter}** / 발행 **{tot_posted}건**"
        f" / 채널 {len(ok)}개{nl}{nl}"
    )

    lines = []
    for r in sorted(ok, key=lambda x: x.get("views") or 0, reverse=True):
        d = r.get("delta")
        dstr = f"({d:+d})" if isinstance(d, int) else ""
        lines.append(
            f"- {r['name']} @{r.get('username','')} · 팔 {r.get('followers',0)}{dstr}"
            f" · 조회 {r.get('views',0)} · 도달 {r.get('reach',0)}"
            f" · 반응 {r.get('total_interactions',0)} · 발행 {r.get('posted',0)}"
        )
    body = nl.join(lines) + nl if lines else ""

    # 파이프라인 이상 신호
    alerts = []
    silent = [r["name"] for r in ok if not r.get("posted")]
    if silent:
        alerts.append("발행 0건: " + ", ".join(silent))
    broken = [f"{r['name']}({r['error']})" for r in rows if r.get("error")]
    if broken:
        alerts.append("조회 실패: " + ", ".join(broken))
    partial = [f"{r['name']}({r.get('insight_error') or r.get('media_error')})"
               for r in rows if r.get("insight_error") or r.get("media_error")]
    if partial:
        alerts.append("일부 지표 실패: " + ", ".join(partial))
    expiring = [f"{r['name']} D-{r['days_left']}"
                for r in rows if isinstance(r.get("days_left"), int) and r["days_left"] <= 14]
    if expiring:
        alerts.append("토큰 만료 임박: " + ", ".join(expiring))
    alert_block = (nl + "**점검 필요**" + nl + nl.join("- " + a for a in alerts) + nl) if alerts else ""

    top_n = _int_env("IG_REPORT_TOP_N", 3)
    all_reels = [(r["name"], m) for r in ok for m in (r.get("reels") or [])]
    all_reels.sort(key=lambda x: x[1].get("views") or 0, reverse=True)
    top_block = ""
    if all_reels and top_n > 0:
        top_block = nl + f"**상위 릴스 TOP{min(top_n, len(all_reels))}** (24h 발행분)" + nl
        for name, m in all_reels[:top_n]:
            top_block += (
                f"- {name} · 조회 {m.get('views',0)} · 좋아요 {m.get('like_count',0)}"
                f" · 댓글 {m.get('comments_count',0)} {m.get('permalink','')}{nl}"
            )
    if not alerts and not broken:
        top_block += nl + "전 채널 이상 없음"

    # 길이 제한으로 채널을 잘라내지 않는다 — 전 채널을 다 보여주고, 넘치면 여러 메시지로 나눈다.
    return head + body + alert_block + top_block


def _split_for_discord(text: str, limit: int = 1900) -> list[str]:
    """디스코드 2000자 한도에 맞춰 **줄 단위**로 쪼갠다(채널 생략 금지).

    한 줄이 limit 을 넘는 비정상 케이스만 강제로 자른다.
    """
    chunks: list[str] = []
    cur = ""
    for line in text.split("\n"):
        while len(line) > limit:                      # 비정상적으로 긴 한 줄
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks or [""]


async def run_report_once(*, dry_run: bool = False) -> dict:
    """24h 인스타 운영 리포트 1회 생성 → 디스코드 전송. dry_run 이면 전송 생략."""
    now = datetime.now(_KST)
    since = now - timedelta(hours=24)
    channels = report_channels()

    rows: list[dict] = []
    async with httpx.AsyncClient() as client:
        for cid in channels:
            try:
                rows.append(await _collect_channel(client, cid, since))
            except Exception as e:  # 채널 하나가 리포트 전체를 죽이지 않게
                rows.append({"cid": cid, "name": _channel_name(cid), "error": str(e)[:60]})

    prev = _load_state()
    content = _build_message(rows, since, now, prev)

    sent = False
    if not dry_run:
        from app.admin.ops.services.discord_notify import notify

        webhook_env = (os.environ.get("IG_REPORT_WEBHOOK_ENV") or "DISCORD_WEBHOOK_IG").strip()
        parts = _split_for_discord(content)
        sent = True
        for i, part in enumerate(parts, 1):
            tag = f"  ({i}/{len(parts)})" if len(parts) > 1 else ""
            ok = await notify(part + tag, env_key=webhook_env)
            sent = sent and ok
            if i < len(parts):
                await asyncio.sleep(1.0)  # 디스코드 레이트리밋 여유
        # 팔로워 스냅샷은 전송 성공 여부와 무관하게 갱신(증감 기준선 유지)
        snap = {
            r["cid"]: {"followers": r.get("followers") or 0, "at": now.isoformat()}
            for r in rows if not r.get("error")
        }
        _save_state({**prev, **snap})

    logger.info("ig_report done channels=%d sent=%s dry=%s", len(rows), sent, dry_run)
    return {
        "channels": len(rows),
        "sent": sent,
        "dry_run": dry_run,
        "content": content,
        "rows": [{k: v for k, v in r.items() if k != "reels"} for r in rows],
    }


async def _loop() -> None:
    while True:
        now = datetime.now(_KST)
        hh, mm = _at()
        nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        await asyncio.sleep(max(1.0, (nxt - now).total_seconds()))
        try:
            await run_report_once()
        except Exception as e:  # 실패해도 루프·앱 유지
            logger.exception("ig_report loop failed: %s", e)


def start() -> None:
    """앱 startup 에서 호출. env 로 켜졌을 때만 백그라운드 태스크 기동."""
    if not _truthy("IG_REPORT_ENABLED"):
        logger.info("ig_report disabled (IG_REPORT_ENABLED != 1)")
        return
    try:
        asyncio.get_running_loop().create_task(_loop())
        hh, mm = _at()
        logger.info("ig_report started (at=%02d:%02d KST, channels=%d)",
                    hh, mm, len(report_channels()))
    except RuntimeError:
        logger.warning("ig_report: 러닝 루프 없음 — 기동 스킵")
