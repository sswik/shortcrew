"""인스타그램 댓글 → 자동 DM(비공개 답장) + 공개 답글 웹훅. 06.운영가이드/08_인스타댓글자동DM.md 참고.

- GET  /webhooks/instagram : 콜백 등록 검증(hub.challenge 에코)
- POST /webhooks/instagram : 댓글 이벤트 수신 → 서명 검증 → 규칙(dm_automations) 매칭 → 공개 답글 + 비공개 DM

토큰은 채널 dict 에 넣지 않고 `CHANNEL_{ID}_IG_*` env 에서 직접 읽는다.
계정 매핑: 웹훅 `entry[].id`(댓글이 달린 IG 비즈니스 계정 ID) == `CHANNEL_{ID}_IG_ACCOUNT_ID`.
규칙 매칭: 그 채널의 활성 규칙 중 (게시물 + 키워드) 조건이 맞는 첫 규칙(최신순)을 실행한다.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import random

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from sqlalchemy import select

from app.admin.ops.channels import get_channels
from app.admin.ops.channels.env_names import channel_env
from models import DmAutomation, SessionLocal

log = logging.getLogger("ig_webhook")

_DEFAULT_DM_TEXT = "댓글 남겨주셔서 감사합니다! 🙌 아래 링크에서 추천 상품을 확인해보세요 👇"


def _api_version() -> str:
    return (os.environ.get("IG_GRAPH_API_VERSION") or "v21.0").strip() or "v21.0"


def _channel_ig_ids(channel_id: str) -> set[str]:
    """채널의 본인 IG ID 집합 — 네이티브 계정 ID + 앱스코프 ID.

    한 IG 계정은 두 ID 를 가진다(`/me` 의 `user_id`=네이티브, `id`=앱스코프).
    웹훅 `entry.id`/`from.id` 가 둘 중 어느 값으로 올지 보장되지 않으므로 둘 다 본인으로 본다.
    """
    return {
        v for v in (
            os.environ.get(channel_env(channel_id, "IG_ACCOUNT_ID"), "").strip(),
            os.environ.get(channel_env(channel_id, "IG_APP_SCOPED_ID"), "").strip(),
        ) if v
    }


def _resolve_ig_channel(account_id: str) -> tuple[dict, str] | None:
    """웹훅 entry.id(IG 계정 ID)로 채널 dict 와 액세스 토큰을 찾는다(없으면 None).

    entry.id 는 네이티브/앱스코프 중 하나로 오므로 두 ID 모두와 대조한다.
    """
    if not account_id:
        return None
    for ch in get_channels():
        cid = (ch.get("channel_id") or "").strip()
        if not cid:
            continue
        if account_id in _channel_ig_ids(cid):
            token = os.environ.get(channel_env(cid, "IG_ACCESS_TOKEN"), "").strip()
            return ch, token
    return None


def _send_account_id(channel_id: str) -> str:
    """Graph API 호출(/messages) 에 쓸 네이티브 IG 계정 ID. 없으면 빈 문자열."""
    return os.environ.get(channel_env(channel_id, "IG_ACCOUNT_ID"), "").strip()


def _dm_text_from_rule(rule: DmAutomation) -> str:
    """규칙의 DM 본문 + 상품 딥링크."""
    msg = (rule.dm_message or "").strip() or _DEFAULT_DM_TEXT
    link = (rule.dm_link or "").strip()
    if link and link not in msg:
        return f"{msg}\n{link}"
    return msg


def _match_rule(db, channel_id: str, media_id: str, text: str) -> DmAutomation | None:
    """채널의 활성 규칙 중 게시물·키워드가 맞는 첫 규칙(최신순). next 미바인딩이면 1회 바인딩."""
    rows = db.scalars(
        select(DmAutomation)
        .where(DmAutomation.channel_id == channel_id, DmAutomation.active.is_(True))
        .order_by(DmAutomation.id.desc())
    ).all()
    text_low = (text or "").lower()
    for r in rows:
        # 게시물 매칭
        if r.target_mode == "specific":
            if not r.ig_media_id or r.ig_media_id != media_id:
                continue
        elif r.target_mode == "next":
            if r.ig_media_id:
                if r.ig_media_id != media_id:
                    continue
            else:
                # 다음 발행 게시물 자동: 첫 댓글 게시물에 1회 바인딩(정밀 baseline은 06.운영가이드/08_인스타댓글자동DM.md C-8).
                if not media_id:
                    continue
                r.ig_media_id = media_id
                db.commit()
        else:
            continue
        # 키워드 매칭
        if r.trigger_type == "keyword":
            kws = [k.lower() for k in json.loads(r.keywords_json or "[]") if k.strip()]
            if not kws or not any(k in text_low for k in kws):
                continue
        return r
    return None


def _send_private_reply(account_id: str, token: str, comment_id: str, text: str, ver: str) -> None:
    """댓글 작성자에게 비공개 답장(DM). 백그라운드 실행."""
    url = f"https://graph.instagram.com/{ver}/{account_id}/messages"
    body = {"recipient": {"comment_id": comment_id}, "message": {"text": text}}
    try:
        r = httpx.post(url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=10.0)
        if r.status_code >= 400:
            log.warning("ig_private_reply_failed comment=%s status=%s body=%s",
                        comment_id, r.status_code, r.text[:500])
        else:
            log.info("ig_private_reply_ok comment=%s", comment_id)
    except httpx.HTTPError as e:
        log.warning("ig_private_reply_error comment=%s err=%s", comment_id, e)


def _send_public_reply(token: str, comment_id: str, text: str, ver: str) -> None:
    """댓글에 공개 답글. 백그라운드 실행."""
    url = f"https://graph.instagram.com/{ver}/{comment_id}/replies"
    try:
        r = httpx.post(url, data={"message": text}, headers={"Authorization": f"Bearer {token}"}, timeout=10.0)
        if r.status_code >= 400:
            log.warning("ig_public_reply_failed comment=%s status=%s body=%s",
                        comment_id, r.status_code, r.text[:500])
        else:
            log.info("ig_public_reply_ok comment=%s", comment_id)
    except httpx.HTTPError as e:
        log.warning("ig_public_reply_error comment=%s err=%s", comment_id, e)


def _valid_signature(raw: bytes, header: str | None) -> bool:
    """X-Hub-Signature-256 을 앱 시크릿으로 HMAC-SHA256 검증(원문 바이트 기준)."""
    secret = (os.environ.get("IG_APP_SECRET") or "").strip()
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


router = APIRouter()


@router.get("/webhooks/instagram")
async def verify(request: Request) -> Response:
    """콜백 등록 검증: verify_token 이 맞으면 hub.challenge 를 그대로 돌려준다."""
    params = request.query_params
    expected = (os.environ.get("IG_WEBHOOK_VERIFY_TOKEN") or "").strip()
    if (
        params.get("hub.mode") == "subscribe"
        and expected
        and params.get("hub.verify_token") == expected
    ):
        return Response(content=params.get("hub.challenge") or "", media_type="text/plain")
    raise HTTPException(status_code=403, detail="verify token mismatch")


@router.post("/webhooks/instagram")
async def receive(request: Request, background_tasks: BackgroundTasks) -> Response:
    """댓글 이벤트 수신: 서명 검증 → 규칙 매칭 → 공개 답글 + DM 예약 후 즉시 200."""
    raw = await request.body()
    if not _valid_signature(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=403, detail="invalid signature")
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid json")

    ver = _api_version()
    db = SessionLocal()
    try:
        for entry in payload.get("entry", []):
            account_id = str(entry.get("id") or "")
            for change in entry.get("changes", []):
                if change.get("field") != "comments":
                    continue
                value = change.get("value") or {}
                comment_id = value.get("id")
                from_id = str((value.get("from") or {}).get("id") or "")
                text = value.get("text") or ""
                media_id = str((value.get("media") or {}).get("id") or "")
                if not comment_id:
                    continue
                resolved = _resolve_ig_channel(account_id)
                if resolved is None:
                    log.warning("ig_comment_unmapped account=%s comment=%s", account_id, comment_id)
                    continue
                channel, token = resolved
                channel_id = str(channel.get("channel_id") or "")
                # 운영 계정 본인 댓글/답글(네이티브·앱스코프 ID 모두) → 루프 방지
                if from_id and from_id in _channel_ig_ids(channel_id):
                    continue
                if not token:
                    log.warning("ig_comment_no_token channel=%s account=%s",
                                channel_id, account_id)
                    continue
                # Graph API 호출은 항상 네이티브 계정 ID 로(entry.id 가 앱스코프여도 안전)
                send_id = _send_account_id(channel_id) or account_id
                rule = _match_rule(db, channel_id, media_id, text)
                if rule is None:
                    log.info("ig_comment_no_rule channel=%s media=%s comment=%s",
                             channel_id, media_id, comment_id)
                    continue
                # 공개 답글(랜덤 변형 1개)
                if rule.public_reply_enabled:
                    variants = [v for v in json.loads(rule.public_reply_variants_json or "[]") if v.strip()]
                    if variants:
                        background_tasks.add_task(_send_public_reply, token, comment_id, random.choice(variants), ver)
                # 비공개 DM
                background_tasks.add_task(
                    _send_private_reply, send_id, token, comment_id, _dm_text_from_rule(rule), ver,
                )
                log.info("ig_comment_matched channel=%s rule=%s comment=%s",
                         channel_id, rule.id, comment_id)
    finally:
        db.close()
    return Response(status_code=200)
