# API 스펙

> shortcrew HTTP 엔드포인트 명세. (근거: `main.py` 라우트, `app/admin/ops/routes/*`, `app/webhooks/instagram.py`)

## 1. 공개 (인증 없음)

| 메서드 | 경로 | 응답 | 설명 |
|--------|------|------|------|
| GET | `/health` | JSON | 헬스체크 |
| GET | `/` | HTML | 인플루언서 홈 |
| GET | `/about` | HTML | 소개 페이지 |
| GET | `/privacy` | HTML | 개인정보처리방침 |
| GET | `/{name_slug}` | HTML | 독립몰 허브(상품 탭) |
| GET | `/{name_slug}/introduce` | HTML | 소개 탭 |
| GET | `/{name_slug}/review` | HTML | 리뷰 목록 탭 |
| GET | `/{name_slug}/review/{review_id}` | HTML | 리뷰 상세 |
| GET | `/shop/{path_slug}` · `/reviews/{...}` | 301 | 레거시 리다이렉트 |
| GET | `/api/mall-products` | JSON | 상품 목록(시트 JSON, 120s 캐시) |
| POST | `/api/click` | JSON | 클릭 로그 적재 |

### POST /api/click
- 입력: `influencer_slug`, `product_id` (필수) / `client_user_agent`, `page_url`, `referrer_snapshot` (선택)
- 처리: `click_logs` 스냅샷 적재 (`static/js/tracking.js`)

### GET /api/mall-products
- 소스: 채널별 Apps Script 웹앱 JSON(`CHANNEL_*_MALL_PRODUCTS_API_URL`, 폴백 `_PRODUCT_DELIVERY_WEBAPP_URL`)
- 썸네일: `COUPANG_IMAGE_WORKER_BASE`(기본 `https://image.shortcrew.co.kr/`)

## 2. 백오피스 HTML (세션 인증)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET/POST | `/admin/login`, POST `/admin/logout` | 인증 |
| GET | `/admin/dashboard` | 대시보드 |
| GET | `/admin/products` | 상품 관리 |
| GET | `/admin/reviews` | 리뷰 목록·필터 |
| GET | `/admin/reviews/new` | 새 리뷰(Toast UI Editor) |
| POST | `/admin/reviews` | 리뷰 생성 |
| GET | `/admin/reviews/{id}` | 관리자 상세(Viewer) |
| GET | `/admin/reviews/{id}/edit` · POST `/admin/reviews/{id}/edit` | 수정 |
| GET | `/admin/reviews/product-options` | 리뷰-상품 연결 옵션 |
| GET | `/admin/influencers` · `/admin/influencers/{slug}/edit` · POST edit | 인플루언서 관리 |
| GET | `/admin/sheets` | 시트 안내 |
| GET | `/admin/logs` | 클릭 로그 |

## 3. 운영 Ops JSON API — prefix `/admin/api/ops`

### 채널 (`/`)
`GET /channels`, `GET /channels/{id}/settings`, `POST /channels/{id}/settings`

### 쿠팡 (`/coupang`)
`GET /search`

### 네이버 (`/naver`)
`GET /trend`

### 시트 (`/sheets`)
`POST /deeplink-preview`, `POST /send`, `GET /items`, `POST /mall-import`, `POST /items/status`

### AI (`/ai`)
| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/curate` | Gemini 상품 큐레이션 |
| POST | `/curate/send-to-history-sheet` | 히스토리 시트 전송 |
| POST | `/review-draft` | **AI 리뷰 초안 생성**(`gemini_review_draft.py`) |

### 몰/클릭 (`/mall`)
`POST /click`, `GET /clicks/recent`, `GET /clicks/summary`

### 쇼츠 리뷰 (`/shorts-review`) — shortcrew 전용
| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/run` | 쇼츠 시트 트리거 리뷰 자동 발행 수동 실행(크론과 동일 파이프라인) |

### DM (`/dm`)
`GET /channels`, `GET /rules`, `POST /rules`, `PATCH /rules/{id}`, `DELETE /rules/{id}`, `GET /media`

## 4. 웹훅 (공개)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/webhooks/instagram` | 검증(verify token) |
| POST | `/webhooks/instagram` | 댓글 이벤트 → 공개 답글 + 자동 DM(두-ID 하드닝, `docs/10`) |

## 공통 규약
- 마운트 prefix `/admin/api/ops`, static `/static`
- 딥링크: 쿠팡 `subId` 고정 `shortcrew`, 공개 링크 `lptag`만
- 접속 로그: 모든 요청 → `logs/access_*.txt`(미들웨어)
