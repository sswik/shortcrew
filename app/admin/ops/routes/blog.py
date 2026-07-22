"""블로그 관리 ops API — 목록·발행/취소·IG 발행·수동 생성.

인증은 `OPS_API_TOKEN`(헤더 `X-Ops-Token`) — 어드민 UI·n8n 공용.
블로그 자동 생성은 브리지 큐레이션(auto_blog)에서, 여기서는 관리·수동 생성·IG 발행.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.deps import get_db
from app.admin.ops.routes.instagram_publish import require_ops_token
from app.admin.ops.services import blog_service
from models import BlogPost, Pump

router = APIRouter()


def _pump_display(db: Session, pump_slug: str) -> str:
    p = db.scalar(select(Pump).where(Pump.name_slug == pump_slug))
    return p.display_name if p else pump_slug


def _post_or_404(db: Session, post_id: int) -> BlogPost:
    post = db.get(BlogPost, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="블로그 글을 찾을 수 없습니다.")
    return post


@router.get("/list")
def list_posts(slug: str = "", db: Session = Depends(get_db), _: None = Depends(require_ops_token)) -> dict:
    """관리용 목록(모든 상태). slug 지정 시 해당 펌프만."""
    q = select(BlogPost).order_by(BlogPost.created_at.desc())
    if (slug or "").strip():
        q = q.where(BlogPost.pump_slug == slug.strip())
    rows = db.scalars(q).all()
    return {
        "count": len(rows),
        "posts": [
            {
                "id": p.id,
                "pump_slug": p.pump_slug,
                "title": p.title,
                "status": p.status,
                "has_image": bool(p.product_image_url),
                "has_youtube": bool(p.youtube_url),
                "ig_media_id": p.ig_media_id or "",
                "url": f"/{p.pump_slug}/blog/{p.id}",
                "created_at": p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else "",
            }
            for p in rows
        ],
    }


class _StatusBody(BaseModel):
    status: str = "published"  # published | draft


@router.post("/{post_id}/status")
def set_status(
    post_id: int, body: _StatusBody, db: Session = Depends(get_db), _: None = Depends(require_ops_token)
) -> dict:
    """몰 노출 상태 토글(published/draft)."""
    post = _post_or_404(db, post_id)
    if body.status not in ("published", "draft"):
        raise HTTPException(status_code=400, detail="status must be published|draft")
    post.status = body.status
    db.commit()
    return {"ok": True, "id": post.id, "status": post.status}


class _PublishIgBody(BaseModel):
    dry_run: bool = False


@router.post("/{post_id}/publish-ig")
async def publish_ig(
    post_id: int, body: _PublishIgBody, db: Session = Depends(get_db), _: None = Depends(require_ops_token)
) -> dict:
    """대표 상품이미지 1장 + 캡션 → 채널 IG 피드 발행. 성공 시 ig_media_id 저장·published."""
    post = _post_or_404(db, post_id)
    if not (post.product_image_url or "").strip():
        raise HTTPException(status_code=400, detail="상품 이미지가 없어 IG 발행 불가(텍스트만 글 금지).")
    channel_id = blog_service.channel_id_for_pump_slug(post.pump_slug)
    if not channel_id:
        raise HTTPException(status_code=400, detail=f"pump_slug '{post.pump_slug}' 에 대응하는 채널이 없습니다.")
    caption = blog_service.build_ig_caption(
        title=post.title,
        excerpt=post.excerpt,
        deeplink=post.product_deeplink,
        pump_display=_pump_display(db, post.pump_slug),
    )
    try:
        result = await blog_service.publish_image_to_ig(
            channel_id=channel_id, image_url=post.product_image_url, caption=caption, dry_run=body.dry_run
        )
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=502, detail=str(e))
    if not body.dry_run:
        post.ig_media_id = str(result.get("media_id") or "")
        post.ig_published_at = datetime.utcnow()
        post.status = "published"
        db.commit()
    return {"ok": True, "id": post.id, "result": result}


class _GenerateBody(BaseModel):
    pump_slug: str
    product_title: str
    product_price: float = 0.0
    product_url: str = ""
    product_image_url: str  # 필수(빈 값이면 서비스가 거부)
    topic: str = ""
    youtube_url: str = ""
    auto_publish: bool = True   # 생성 즉시 몰 노출(published)
    auto_ig: bool = False        # 생성 후 IG 자동 발행


@router.post("/generate")
async def generate_post(
    body: _GenerateBody, db: Session = Depends(get_db), _: None = Depends(require_ops_token)
) -> dict:
    """상품 1개로 블로그 글 수동 생성(Gemini). 상품이미지 필수. 옵션: 즉시 발행·IG 발행."""
    try:
        fields = await blog_service.generate_blog_fields(
            pump_slug=body.pump_slug,
            pump_display=_pump_display(db, body.pump_slug),
            product_title=body.product_title,
            product_price=body.product_price,
            product_url=body.product_url,
            product_image_url=body.product_image_url,
            topic=body.topic,
            youtube_url=body.youtube_url,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    fields["status"] = "published" if body.auto_publish else "draft"
    post = BlogPost(**fields)
    db.add(post)
    db.commit()
    out = {"ok": True, "id": post.id, "status": post.status, "url": f"/{post.pump_slug}/blog/{post.id}"}
    if body.auto_ig and post.status == "published":
        try:
            channel_id = blog_service.channel_id_for_pump_slug(post.pump_slug)
            caption = blog_service.build_ig_caption(
                title=post.title, excerpt=post.excerpt, deeplink=post.product_deeplink,
                pump_display=_pump_display(db, post.pump_slug),
            )
            res = await blog_service.publish_image_to_ig(
                channel_id=channel_id, image_url=post.product_image_url, caption=caption
            )
            post.ig_media_id = str(res.get("media_id") or "")
            post.ig_published_at = datetime.utcnow()
            db.commit()
            out["ig"] = {"ok": True, "media_id": post.ig_media_id}
        except Exception as e:  # IG 실패해도 글 생성은 유지
            out["ig"] = {"ok": False, "error": str(e)[:120]}
    return out
