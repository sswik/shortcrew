from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


DATABASE_URL = "sqlite:///./database.db"


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


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
