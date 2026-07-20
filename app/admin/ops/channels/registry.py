"""채널 등록부: 순서·목록만 여기서 관리.

신규 채널 절차
--------------
1. `roster/pumps_channels.py` 에 `build_NN()` 을 추가한다(`channel_id` 는 `.env` 의 `CHANNEL_NN_*` 와 맞춘다). 트렌드 시드는 `_CHANNEL_TREND_SEEDS[NN]` 로 넣는다.
2. 아래 `CHANNEL_BUILDERS` 튜플에 원하는 순서로 추가한다.

빌더 dict 스키마(ops API·시트·몰 연동과 호환)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- channel_id: str   … `.env` 접두(`CHANNEL_{ID}_*`)와 동일 (예: `05`, `24`)
- name: str         … 백오피스 표시명. 기본은 `CHANNEL_{ID}_TAB` 에서 `-상품` 을 뗀 값
- google_sheet_id / sheet_tab_name / history_sheet_id / history_sheet_tab
- product_delivery_url / mall_products_api_url / mall_products_channel_param
- mall_pump_slug: str … `pumps.name_slug` 또는 `shop_path_slug` 와 대소문자 무시 매칭
- naver_category_id: list[str] / trend_keywords: list[str] / monitor_keywords: list[str]

02~04 = 인플루언서 몰(골프·테니스·쇼핑), 05~37 = 펌프 몰. 딥링크 subId 는 `shortcrew` 고정.
"""
from __future__ import annotations

from collections.abc import Callable

from .roster import pumps_channels

ChannelBuilder = Callable[[], dict]

CHANNEL_BUILDERS: tuple[ChannelBuilder, ...] = (
    pumps_channels.build_02,  # 골프(오세련)
    pumps_channels.build_03,  # 테니스(왕세림)
    pumps_channels.build_04,  # 쇼핑(한소율)
    pumps_channels.build_05,
    pumps_channels.build_07,
    pumps_channels.build_09,
    pumps_channels.build_10,
    pumps_channels.build_11,
    pumps_channels.build_12,
    pumps_channels.build_13,
    pumps_channels.build_14,
    pumps_channels.build_15,
    pumps_channels.build_16,
    pumps_channels.build_17,
    pumps_channels.build_18,
    pumps_channels.build_19,
    pumps_channels.build_20,
    pumps_channels.build_21,
    pumps_channels.build_22,
    pumps_channels.build_23,
    pumps_channels.build_24,
    pumps_channels.build_25,
    pumps_channels.build_26,
    pumps_channels.build_27,
    pumps_channels.build_28,
    pumps_channels.build_29,
    pumps_channels.build_30,
    pumps_channels.build_31,
    pumps_channels.build_32,
    pumps_channels.build_33,
    pumps_channels.build_34,
    pumps_channels.build_35,
    pumps_channels.build_36,
    pumps_channels.build_37,
)
