from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def _load_dotenv_for_db() -> None:
    """models 를 단독 import(scripts/tests)해도 `.env` 의 DATABASE_URL 을 읽도록 보강.
    값이 이미 환경에 있으면(앱 부팅 시 main._load_env_file 등) 건드리지 않는다."""
    if (os.environ.get("DATABASE_URL") or "").strip():
        return
    p = Path(__file__).resolve().parent / ".env"
    if not p.is_file():
        return
    try:
        from dotenv import dotenv_values
    except Exception:
        return
    for key, val in dotenv_values(p).items():
        if val is None:
            continue
        cur = os.environ.get(key)
        if cur is None or cur.strip() == "":
            os.environ[key] = val


_load_dotenv_for_db()

# DB 연결은 `.env` 의 DATABASE_URL 로 결정한다(필수). 예) mysql+pymysql://sswik:****@127.0.0.1:3306/crews
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL 이 설정되지 않았습니다. .env 의 DATABASE_URL(MySQL crews) 을 확인하라.")


class Base(DeclarativeBase):
    pass


class Influencer(Base):
    __tablename__ = "influencers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name_slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    # 채널 매칭·레거시용. 브라우저 공개 URL은 `/{name_slug}` (예: /soccer). 예전 슬러그는 `shop_path_slug`로 조회.
    shop_path_slug: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True, default=None)
    display_name: Mapped[str] = mapped_column(String(200))
    profile_image: Mapped[str] = mapped_column(String(255), default="")
    bio: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    youtube_url: Mapped[str] = mapped_column(String(500), default="")
    instagram_url: Mapped[str] = mapped_column(String(500), default="")
    tiktok_url: Mapped[str] = mapped_column(String(500), default="")
    cover_image: Mapped[str] = mapped_column(String(500), default="")
    profile_meta_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    mall_theme_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    products: Mapped[list["Product"]] = relationship(back_populates="influencer")
    reviews: Mapped[list["Review"]] = relationship(back_populates="influencer")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    influencer_slug: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("influencers.name_slug", ondelete="CASCADE"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255))
    price: Mapped[float] = mapped_column(Float)
    image_url: Mapped[str] = mapped_column(String(500))
    coupang_url: Mapped[str] = mapped_column(String(500))

    influencer: Mapped["Influencer"] = relationship(back_populates="products")
    reviews: Mapped[list["Review"]] = relationship(back_populates="product")


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint(
            "influencer_slug",
            "source_youtube_video_id",
            name="uq_reviews_influencer_youtube_video",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    product_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("products.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    influencer_slug: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("influencers.name_slug", ondelete="CASCADE"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    source_youtube_video_id: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        default=None,
    )
    # DB products FK 없이 시트에서만 고른 경우: 공개 구매 링크·메타용
    sheet_product_title: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    sheet_product_deeplink: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)

    influencer: Mapped["Influencer"] = relationship(back_populates="reviews")
    product: Mapped["Product | None"] = relationship(back_populates="reviews")


class ClickLog(Base):
    __tablename__ = "click_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    influencer_slug: Mapped[str] = mapped_column(String(100), index=True)
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    raw_product_ref: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)
    product_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    deep_link_snapshot: Mapped[str | None] = mapped_column(String(1200), nullable=True, default=None)
    client_user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    page_url: Mapped[str | None] = mapped_column(String(800), nullable=True, default=None)
    referrer_snapshot: Mapped[str | None] = mapped_column(String(600), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DmAutomation(Base):
    """인스타 댓글→자동 DM 규칙(인포크식). 06.운영가이드/08_인스타댓글자동DM.md C 참고."""

    __tablename__ = "dm_automations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    channel_id: Mapped[str] = mapped_column(String(8), index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    # 게시물 타게팅: specific(직접 선택) | next(다음 발행 게시물 자동)
    target_mode: Mapped[str] = mapped_column(String(16), default="specific")
    ig_media_id: Mapped[str | None] = mapped_column(String(40), nullable=True, default=None)
    media_permalink: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    media_thumbnail: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    next_baseline_ts: Mapped[str | None] = mapped_column(String(40), nullable=True, default=None)
    # 트리거: any(모든 댓글) | keyword(특정 키워드)
    trigger_type: Mapped[str] = mapped_column(String(16), default="keyword")
    keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    # 공개 답글(댓글에 답글): 랜덤 변형 최대 3
    public_reply_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    public_reply_variants_json: Mapped[str] = mapped_column(Text, default="[]")
    # DM 내용(상품 선택 → 딥링크 자동)
    dm_message: Mapped[str] = mapped_column(Text, default="")
    dm_product_ref: Mapped[str | None] = mapped_column(String(160), nullable=True, default=None)
    dm_product_title: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    dm_link: Mapped[str] = mapped_column(String(800), default="")
    # 옵션/상태
    follower_only: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# MySQL: 끊긴 커넥션 자동 감지(pre_ping) + 오래된 커넥션 재활용.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
