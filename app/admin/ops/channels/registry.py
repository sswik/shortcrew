"""채널 등록부: 순서·목록만 여기서 관리.

신규 채널 절차
--------------
1. `roster/` 아래에 채널당 모듈을 추가한다(예: `roster/soccer.py` — `channel_id` 는 숫자 `201` 등으로 `.env` 의 `CHANNEL_201_*` 와 맞춘다).
2. 그 모듈에 `def build() -> dict:` 를 두고, 아래 스키마에 맞는 dict 를 반환한다.

필수 키(기존 ops API·시트 연동과 호환)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- channel_id: str   … API·로그에서 쓰는 고유 ID (영문·숫자·밑줄 권장)
- name: str         … 백오피스·드롭다운 표시명. **`○○○픽(인플루언서분야)`** 형식(예: `왕세림픽(테니스인플루언서)`)
- google_sheet_id: str
- sheet_tab_name: str
- history_sheet_id: str   … 없으면 COMMON_HISTORY_FILE_ID 와 동일하게 두면 됨
- history_sheet_tab: str
- product_delivery_url: str (선택) … 시트 전송 성공 후 JSON POST할 Apps Script URL. 채널별로 `roster/*.py`·`env_names.channel_env` 규칙의 env로 설정
- mall_products_api_url: str (선택) … 공개 몰 `/{name_slug}` 이 **브라우저에서** 상품 JSON을 GET할 주소(sample/ops `config.apiUrl`). roster 에서 env만 넣을 때 **비어 있으면 `product_delivery_url`과 동일 값으로 폴백**(한 웹앱에 doGet+doPost). 둘 다 비우면 몰에 상품 안내 문구만 표시
- mall_products_channel_param: str (선택) … 웹앱 `?channel=` 에 넣을 문자열. 비우면 `channel_id`(예: `201`). 샘플 `APPS_SCRIPT_CHANNEL` 과 같아야 할 때 env `CHANNEL_*_MALL_PRODUCTS_CHANNEL_PARAM` 로 지정
- mall_influencer_slug: str (선택) … `influencers.name_slug` **또는** `shop_path_slug` 와 **대소문자 무시로** 일치하는 토큰이면 연결. **쉼표·세미콜론**으로 여러 슬러그 가능(예: `soccer,jimin`). 로스터 채널이 **딱 1개**이고 몰 URL이 있으면, 슬러그가 안 맞아도 그 채널로 폴백한다(단일 몰).
- naver_category_id: list[str]  … 네이버 쇼핑 카테고리 ID
- trend_keywords: list[str]
- monitor_keywords: list[str]   … 없으면 []

3. 아래 `CHANNEL_BUILDERS` 튜플에 `from .roster import 새모듈` 후 `새모듈.build` 를 **원하는 순서로** 추가한다.
"""
from __future__ import annotations

from collections.abc import Callable

from .roster import golf, health, science, shopping, space, tech, tennis

# 전 인플루언서 3xx 리넘버 완료. tech.py = 옛 safety.py(안지아 105→305, slug safety→tech).
ChannelBuilder = Callable[[], dict]

CHANNEL_BUILDERS: tuple[ChannelBuilder, ...] = (
    golf.build,      # 302 오세련(골프)
    tennis.build,    # 303 왕세림(테니스)
    shopping.build,  # 304 한소율(쇼핑)
    tech.build,      # 305 안지아(테크)
    science.build,   # 310 정세윤(사이언스)
    space.build,     # 311 지서아(스페이스)
    health.build,    # 315 유슬기(헬스)
)
