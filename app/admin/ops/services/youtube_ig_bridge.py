"""유튜브→인스타 크로스포스트 서비스 (전용).

배경: 이 플로우를 구동하는 n8n 은 **다른 n8n 클라우드**라, 기존 `/instagram/publish-reel`
과 분리된 **전용 엔드포인트**로 둔다(라우트: `app/admin/ops/routes/crosspost.py`).

역할 분담:
  - YouTube 업로드  ← n8n `youTube`(OAuth2) 노드
  - 영상 공개 URL   ← n8n(Drive 공개 등) 이 준비 (파일 소유 크리덴셜이 n8n 이므로)
  - IG 릴스 발행    ← **여기(shortcrew)**: 컨테이너 생성 → 인코딩 폴링 → media_publish

당일 신규·과거영상 백필 둘 다 이 함수를 호출한다. Salog 는 참고만 했고 코드는 섞지 않았다.
"""
from __future__ import annotations

import asyncio
import os

import httpx

from app.admin.ops.routes.dm import _ig_account

# Reels 인코딩 폴링(엔드포인트가 끝까지 대기 후 발행까지 반환).
_POLL_INTERVAL_S = 3.0
_POLL_MAX_TRIES = 60  # 약 3분
# 컨테이너 ERROR 는 IG측 일시 인코딩 실패가 잦아 컨테이너 재생성 1회 재시도.
_CONTAINER_MAX_ATTEMPTS = 2
_CONTAINER_RETRY_WAIT_S = 5.0


def _graph_version() -> str:
    return (os.environ.get("IG_GRAPH_API_VERSION") or "v21.0").strip() or "v21.0"


def _thumb_offset_ms() -> str | None:
    """릴스 커버로 쓸 프레임 시점(ms). 인트로 음영을 건너뛰기 위한 기본 2000ms.

    `IG_REEL_THUMB_OFFSET_MS` 로 조절(0 또는 비숫자면 미지정 → IG 기본 첫 프레임).
    """
    raw = (os.environ.get("IG_REEL_THUMB_OFFSET_MS") or "2000").strip()
    return raw if raw.isdigit() and int(raw) > 0 else None


async def publish_reel_to_ig(
    *,
    channel_id: str,
    video_url: str,
    caption: str = "",
    share_to_feed: bool = True,
    dry_run: bool = False,
) -> dict:
    """공개 영상 직링크 → 채널 IG 릴스 발행. media_id 반환.

    channel_id 는 00식 채널 id(02~37). IG 계정/토큰은 `CHANNEL_{id}_IG_*` env.
    """
    cid = (channel_id or "").strip()
    vurl = (video_url or "").strip()
    if not cid or not vurl:
        raise ValueError("channel_id, video_url required")
    acct, token = _ig_account(cid)
    if not acct or not token:
        raise ValueError(f"channel {cid} has no IG account/token")

    ver = _graph_version()
    base = f"https://graph.instagram.com/{ver}"
    create_payload = {
        "media_type": "REELS",
        "video_url": vurl,
        "caption": caption or "",
        "share_to_feed": "true" if share_to_feed else "false",
    }
    _thumb = _thumb_offset_ms()
    if _thumb:
        create_payload["thumb_offset"] = _thumb
    if dry_run:
        return {
            "dry_run": True,
            "channel_id": cid,
            "ig_account_id": acct,
            "create_url": f"{base}/{acct}/media",
            "create_payload": create_payload,
            "publish_url": f"{base}/{acct}/media_publish",
        }

    from app.admin.ops.services import discord_notify

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            creation_id = ""
            status = ""
            last_detail = ""
            # 1~2) 컨테이너 생성 + 인코딩 폴링. 컨테이너 ERROR/타임아웃은 IG측 일시장애가 잦아 1회 재시도.
            for attempt in range(_CONTAINER_MAX_ATTEMPTS):
                r = await client.post(f"{base}/{acct}/media", data={**create_payload, "access_token": token})
                if r.status_code >= 400:
                    raise RuntimeError(f"graph create {r.status_code}: {r.text[:300]}")
                creation_id = str(r.json().get("id") or "").strip()
                if not creation_id:
                    raise RuntimeError(f"no creation id: {r.text[:200]}")

                status = ""
                for _try in range(_POLL_MAX_TRIES):
                    # status 필드까지 폴링 → 실패 시 IG 상세 사유(에러코드/메시지) 확보(진단·알림)
                    s = await client.get(
                        f"{base}/{creation_id}",
                        params={"fields": "status_code,status", "access_token": token},
                    )
                    if s.status_code < 400:
                        info = s.json()
                        status = str(info.get("status_code") or "").upper()
                        last_detail = str(info.get("status") or "")
                        if status == "FINISHED":
                            break
                        if status in ("ERROR", "EXPIRED"):
                            break
                    await asyncio.sleep(_POLL_INTERVAL_S)

                if status == "FINISHED":
                    break
                # ERROR/EXPIRED/타임아웃 — 마지막 시도가 아니면 컨테이너 재생성 후 재시도
                if attempt < _CONTAINER_MAX_ATTEMPTS - 1:
                    await asyncio.sleep(_CONTAINER_RETRY_WAIT_S)
                    continue
                if status in ("ERROR", "EXPIRED"):
                    raise RuntimeError(f"container {status}: {last_detail[:300] or s.text[:200]}")
                raise RuntimeError(f"container not ready (last={status}): {last_detail[:200]}")

            # 3) 발행
            p = await client.post(
                f"{base}/{acct}/media_publish",
                data={"creation_id": creation_id, "access_token": token},
            )
            if p.status_code >= 400:
                raise RuntimeError(f"graph publish {p.status_code}: {p.text[:300]}")
            media_id = str(p.json().get("id") or "").strip()
            if not media_id:
                raise RuntimeError(f"publish failed: {p.text[:200]}")
    except Exception as e:
        # 발행 실패 → 통합 실패 알림(알림 자체는 발행 결과에 영향 주지 않고 예외 재전파)
        await discord_notify.notify(
            f"🔴 인스타 업로드 실패 [{cid}]: {str(e)[:200]}",
            env_key="DISCORD_WEBHOOK_FAIL",
        )
        raise

    # 업로드 완료 → 전용 디스코드 채널 알림(실패해도 발행 결과엔 영향 없음)
    await discord_notify.notify(
        f"📸 인스타 업로드 완료 [{cid}] media_id={media_id}",
        env_key="DISCORD_WEBHOOK_IG",
    )

    return {"ok": True, "channel_id": cid, "creation_id": creation_id, "media_id": media_id}
