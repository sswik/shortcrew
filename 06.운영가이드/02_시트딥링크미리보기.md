# 02 — 시트 딥링크·미리보기

백오피스 구글 시트 연동의 **딥링크 생성 규칙**과 **미리보기/전송 API 흐름**을 정리한 내용이다.

## 핵심 변경

- 딥링크 API 요청의 `subId`는 채널/상품별 계산 없이 **고정값 `shortcrew`** 를 사용한다.
- 시트 파이프라인에서 `subId` 표시/전달은 제거했다.
  - 미리보기/전송 응답의 `expected_sub_id` 제거
  - 프론트 확정 목록의 `subId` 병합/표시 제거
  - 시트 K열은 **레거시 예약 열**로 비워서 쓴다

## 라우트: `app/admin/ops/routes/sheets.py`

- **`_enrich_products_with_deeplinks`**: 상품마다 정규 VP URL 생성. 클라이언트가 **비어 있지 않은 `deepLink`**를 내면 해당 상품은 **쿠팡 `generate_deeplinks` 호출 생략** (레이트 리밋 절약).
- **`POST /sheets/deeplink-preview`**: 시트 append 없이 딥링크·`mall_shop_url`·`coupang_api_called` 반환. 실패 시 409.
- **`POST /sheets/send`**: `get_db` 주입, 동일 헬퍼 사용. 웹훅 JSON에 **`mall_shop_url`** 필드 추가.
- 상대 import(`..services`, `..channels`) 및 타입 정리(`Generator` 반환, `Review` 연관은 모델 쪽).

## 프론트: `static/js/admin-products.js`

- 확정 목록 변경 시 **디바운스(약 450ms)** 로 `POST .../sheets/deeplink-preview` 호출 (`409`는 `fetch`로 본문 처리).
- 응답으로 `deepLink`를 목록에 병합한다.
- 시트 전송 시 같은 `confirmedList`를 내면 서버가 쿠팡 API를 건너뛸 수 있다.

## 환경 변수 (예시)

- [`.env.example`](../.env.example): `PUBLIC_SITE_URL`, `COUPANG_PARTNERS_LPTAG` 등.

## 테스트

- [`tests/test_smoke.py`](../tests/test_smoke.py): OpenAPI에 `/admin/api/ops/sheets/deeplink-preview` 포함 여부.
