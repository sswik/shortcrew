"""JSON API: 쿠팡 검색, 네이버 트렌드, 구글 시트 전송, 채널 설정.

도메인별 라우트는 `app.admin.ops.routes` 패키지에 두고 여기서만 조합한다.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.admin.ops.routes import ai as ai_routes
from app.admin.ops.routes import blog as blog_routes
from app.admin.ops.routes import bridge as bridge_routes
from app.admin.ops.routes import channels as channels_routes
from app.admin.ops.routes import coupang as coupang_routes
from app.admin.ops.routes import dm as dm_routes
from app.admin.ops.routes import instagram_publish as instagram_publish_routes
from app.admin.ops.routes import mall as mall_routes
from app.admin.ops.routes import naver as naver_routes
from app.admin.ops.routes import sheets as sheets_routes

router = APIRouter()

router.include_router(channels_routes.router, tags=["admin-ops"])
router.include_router(coupang_routes.router, prefix="/coupang", tags=["admin-ops"])
router.include_router(naver_routes.router, prefix="/naver", tags=["admin-ops"])
router.include_router(sheets_routes.router, prefix="/sheets", tags=["admin-ops"])
router.include_router(ai_routes.router, prefix="/ai", tags=["admin-ops"])
router.include_router(mall_routes.router, prefix="/mall", tags=["admin-ops"])
router.include_router(dm_routes.router, prefix="/dm", tags=["admin-ops"])
router.include_router(instagram_publish_routes.router, prefix="/instagram", tags=["admin-ops"])
router.include_router(bridge_routes.router, prefix="/bridge", tags=["admin-ops"])
router.include_router(blog_routes.router, prefix="/blog", tags=["admin-ops"])
