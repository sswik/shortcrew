"""인스타 댓글 → 자동 DM 규칙 CRUD + 게시물 불러오기(Graph 프록시). 06.운영가이드/08_인스타댓글자동DM.md C 참고.

상품 목록은 별도 API 없이 프론트가 기존 `/api/mall-products?channel_id=` 를 재사용한다.
토큰은 채널 dict 에 넣지 않고 `CHANNEL_{ID}_IG_*` env 에서 직접 읽으며, 클라이언트로 내려보내지 않는다.
"""
from __future__ import annotations

import json
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.auth import require_admin
from app.admin.deps import get_db
from app.admin.ops.channels import get_channels
from app.admin.ops.channels.env_names import channel_env
from models import DmAutomation

router = APIRouter()

_TARGET_MODES = ("specific", "next")
_TRIGGER_TYPES = ("any", "keyword")


def _ig_account(cid: str) -> tuple[str, str]:
    """채널 IG 계정 ID·토큰. 토큰은 자동갱신 저장소(refresh본) 우선, 없으면 env fallback."""
    cid = (cid or "").strip()
    if not cid:
        return "", ""
    from app.admin.ops.services.ig_token_refresh import current_token

    return (
        os.environ.get(channel_env(cid, "IG_ACCOUNT_ID"), "").strip(),
        current_token(cid),
    )


def _rule_to_dict(r: DmAutomation) -> dict:
    return {
        "id": r.id,
        "channel_id": r.channel_id,
        "name": r.name,
        "target_mode": r.target_mode,
        "ig_media_id": r.ig_media_id,
        "media_permalink": r.media_permalink,
        "media_thumbnail": r.media_thumbnail,
        "trigger_type": r.trigger_type,
        "keywords": json.loads(r.keywords_json or "[]"),
        "public_reply_enabled": r.public_reply_enabled,
        "public_reply_variants": json.loads(r.public_reply_variants_json or "[]"),
        "dm_message": r.dm_message,
        "dm_product_ref": r.dm_product_ref,
        "dm_product_title": r.dm_product_title,
        "dm_link": r.dm_link,
        "follower_only": r.follower_only,
        "active": r.active,
    }


class DmRuleBody(BaseModel):
    channel_id: str
    name: str = ""
    target_mode: str = "specific"
    ig_media_id: str | None = None
    media_permalink: str | None = None
    media_thumbnail: str | None = None
    trigger_type: str = "keyword"
    keywords: list[str] = []
    public_reply_enabled: bool = True
    public_reply_variants: list[str] = []
    dm_message: str = ""
    dm_product_ref: str | None = None
    dm_product_title: str | None = None
    dm_link: str = ""
    follower_only: bool = False
    active: bool = True


def _apply_body(r: DmAutomation, body: DmRuleBody) -> None:
    r.channel_id = body.channel_id.strip()
    r.name = (body.name or "").strip()
    r.target_mode = body.target_mode if body.target_mode in _TARGET_MODES else "specific"
    r.ig_media_id = (body.ig_media_id or "").strip() or None
    r.media_permalink = (body.media_permalink or "").strip() or None
    r.media_thumbnail = (body.media_thumbnail or "").strip() or None
    r.trigger_type = body.trigger_type if body.trigger_type in _TRIGGER_TYPES else "keyword"
    r.keywords_json = json.dumps([k.strip() for k in body.keywords if k.strip()], ensure_ascii=False)
    r.public_reply_enabled = bool(body.public_reply_enabled)
    variants = [v.strip() for v in body.public_reply_variants if v.strip()][:3]
    r.public_reply_variants_json = json.dumps(variants, ensure_ascii=False)
    r.dm_message = body.dm_message or ""
    r.dm_product_ref = (body.dm_product_ref or "").strip() or None
    r.dm_product_title = (body.dm_product_title or "").strip() or None
    r.dm_link = (body.dm_link or "").strip()
    r.follower_only = bool(body.follower_only)
    r.active = bool(body.active)


@router.get("/channels")
async def ig_channels(_: None = Depends(require_admin)):
    """IG 계정이 설정된 채널만(드롭다운용). 토큰은 내려보내지 않는다."""
    out = []
    for ch in get_channels():
        cid = (ch.get("channel_id") or "").strip()
        if not cid:
            continue
        acct, token = _ig_account(cid)
        if not acct:
            continue
        out.append({
            "channel_id": cid,
            "name": ch.get("name") or cid,
            "ig_username": os.environ.get(channel_env(cid, "IG_USERNAME"), "").strip(),
            "has_token": bool(token),
        })
    return {"channels": out}


@router.get("/rules")
async def list_rules(
    channel_id: str = "",
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    q = select(DmAutomation)
    if channel_id.strip():
        q = q.where(DmAutomation.channel_id == channel_id.strip())
    rows = db.scalars(q.order_by(DmAutomation.id.desc())).all()
    return {"rules": [_rule_to_dict(r) for r in rows]}


@router.post("/rules")
async def create_rule(
    body: DmRuleBody,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    if not body.channel_id.strip():
        raise HTTPException(status_code=400, detail="channel_id required")
    r = DmAutomation()
    _apply_body(r, body)
    db.add(r)
    db.commit()
    db.refresh(r)
    return _rule_to_dict(r)


@router.patch("/rules/{rule_id}")
async def update_rule(
    rule_id: int,
    body: DmRuleBody,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    r = db.get(DmAutomation, rule_id)
    if r is None:
        raise HTTPException(status_code=404, detail="rule not found")
    _apply_body(r, body)
    db.commit()
    db.refresh(r)
    return _rule_to_dict(r)


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    r = db.get(DmAutomation, rule_id)
    if r is None:
        raise HTTPException(status_code=404, detail="rule not found")
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.get("/media")
async def list_media(
    channel_id: str = "",
    after: str = "",
    _: None = Depends(require_admin),
):
    """채널 IG 계정의 게시물 목록(Graph /media 프록시). 토큰은 서버에만."""
    acct, token = _ig_account(channel_id)
    if not acct or not token:
        raise HTTPException(status_code=400, detail="channel has no IG account/token")
    ver = (os.environ.get("IG_GRAPH_API_VERSION") or "v21.0").strip() or "v21.0"
    params = {
        "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp",
        "limit": "24",
    }
    if after.strip():
        params["after"] = after.strip()
    url = f"https://graph.instagram.com/{ver}/{acct}/media"
    try:
        r = httpx.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=10.0)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"graph error: {e}")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"graph {r.status_code}: {r.text[:300]}")
    data = r.json()
    items = []
    for m in data.get("data", []):
        items.append({
            "id": m.get("id"),
            "caption": (m.get("caption") or "")[:140],
            "media_type": m.get("media_type"),
            "thumbnail": m.get("thumbnail_url") or m.get("media_url"),
            "permalink": m.get("permalink"),
            "timestamp": m.get("timestamp"),
        })
    next_after = ((data.get("paging") or {}).get("cursors") or {}).get("after", "")
    return {"media": items, "after": next_after}
