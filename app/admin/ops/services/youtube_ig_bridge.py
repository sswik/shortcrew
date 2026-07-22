"""[구조 스텁] 유튜브 영상 발행 + 연결 인스타 자동 업로드 브리지.

⚠️ 이 모듈은 **구조 세팅(스캐폴드)** 이다. 실제 발행 로직 연결·최종 n8n JSON 반영은
   운영자가 확인 후 진행한다. Salog(n8n-sample/Salog/10-*)는 **참고만** 했고 코드는 섞지 않았다.

설계 흐름 (06.운영가이드/12_유튜브발행_인스타자동업로드.md):
  1) 렌더 완료 영상(공개 직링크; Drive 공개 URL 등)  ← n8n 이 준비
  2) YouTube 업로드  ← **n8n `youTube`(OAuth2) 노드가 담당**(채널별 크리덴셜). 서버는 관여 안 함.
  3) 연결 인스타에 릴스 자동 업로드  ← **기존 `POST /admin/api/ops/instagram/publish-reel` 재사용**
     (채널 IG 계정=`CHANNEL_{id}_IG_*`, 컨테이너 생성→인코딩 폴링→발행까지 서버가 처리)
  4) (선택) 발행 결과(youtube_id/ig_media_id) 앱으로 ingest → 시트/DB 기록

즉 shortcrew 는 **IG 발행만** 책임지고(이미 구현됨), YouTube 업로드는 n8n 이 맡는다.
아래 함수들은 그 경계를 코드로 명시한 스텁이다(미배선).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PublishPlan:
    """한 영상의 발행 계획(스텁 반환용)."""

    channel_id: str
    video_public_url: str
    caption: str
    # YouTube 업로드는 n8n youTube 노드가 수행 — 서버는 결과만 ingest.
    youtube_by: str = "n8n(youTube OAuth node)"
    instagram_by: str = "POST /admin/api/ops/instagram/publish-reel"


def build_publish_plan(*, channel_id: str, video_public_url: str, caption: str = "") -> PublishPlan:
    """발행 계획 dict(스텁). 실제 호출은 n8n(YouTube) + publish-reel(IG)로 분리 수행."""
    return PublishPlan(channel_id=channel_id, video_public_url=video_public_url, caption=caption)


# --- 배선 예정(스텁) ---
# async def upload_to_youtube(...):  # → n8n youTube 노드가 담당하므로 서버 구현 안 함(문서 참조).
# async def crosspost_to_instagram(channel_id, video_public_url, caption):
#     """기존 instagram_publish.publish_reel 을 그대로 호출하면 된다(별도 구현 불필요)."""
#     from app.admin.ops.routes.instagram_publish import PublishReelBody, publish_reel
#     return await publish_reel(PublishReelBody(channel_id=channel_id, video_url=video_public_url, caption=caption))
