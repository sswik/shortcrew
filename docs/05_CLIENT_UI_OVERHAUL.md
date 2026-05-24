# 클라이언트 UI 전면 개편 (05)

## 목표

- 시각: **카페24식 모바일 퍼스트** 표준 쇼핑몰 UX — **Pretendard**(공개 클라이언트), 딥 퍼플 `#5f0080`, 보조면 `#f4f4f4`(`--surface-muted`), 슬림 스티키 헤더(52px), 상품 **2열·3:4** 썸네일, **5개/페이지** 페이지네이션, 타이트한 랭킹 카드.
- 기술: 공개 페이지는 **단일** [static/css/style.css](static/css/style.css) + Jinja([app/client/templates](app/client/templates)). **관리자(백오피스)**는 Tailwind 템플릿에서 **Pretendard** 유지([layout.html](../app/admin/templates/layout.html), [login.html](../app/admin/templates/login.html)).
- **절대 보존**: [static/js/tracking.js](static/js/tracking.js)의 `data-track-click` / `data-influencer` / `data-product-id` 계약. [static/js/shop-products.js](static/js/shop-products.js)의 `withCoupangPartnerQuery`, `extractCoupangProductId`, fetch·JSON 파싱·에러 메시지·페이지네이션(슬라이스·재렌더) 흐름 — **URL/lptag 규칙은 변경하지 않음**(페이지당 개수만 조정 가능).

## 트래킹·URL 처리 원칙

1. **시트 상품(몰)**: `data-product-id`는 기존처럼 쿠팡 VP 경로/ctag에서 추출한 문자열(없으면 `"0"`). `/api/click`은 정수로 파싱하므로 DB `products.id`와 다를 수 있음(기존과 동일).
2. **리뷰 상세 구매**: DB `Review.product_id`를 `data-product-id`에 사용. `href`는 서버에서 `Product.coupang_url`에 파트너스 쿼리(`lptag`)를 보강한 `buy_url`만 사용(JS 이중 보강 없음). 상단 인라인 CTA + 하단 `position: fixed` 도크에 **동일 속성** 유지.

## 데이터 모델

`Influencer`에 공개 프로필용 필드 추가(마이그레이션은 `main.py`의 SQLite `ALTER` 패턴).

| 필드 | 설명 |
|------|------|
| `bio` | 소개 (Text, nullable) |
| `youtube_url` | 유튜브 (String) |
| `instagram_url` | 인스타 (String) |
| `cover_image` | 몰 상단 커버 이미지 URL (String) |

## 수정 파일 체크리스트 (카페24 정렬 기준)

| 파일 | 내용 |
|------|------|
| [models.py](../models.py) | 위 컬럼 |
| [main.py](../main.py) | `create_all`, `shop`에 `reviews`, `review_detail`에 `joinedload`·`buy_url`·URL 보강 헬퍼, 인플 편집 라우트 |
| [app/client/templates/base.html](../app/client/templates/base.html) | Pretendard CDN, Font Awesome, `body_extra` 블록, **52px** 스티키 헤더, `.container` 안 **브랜드(로고+텍스트)만** — 글로벌 상단 텍스트/아이콘 네비 없음 |
| [app/client/templates/home.html](../app/client/templates/home.html) | `hero--dense`, `home-creators`, 바이오 truncate 길이 |
| [app/client/templates/shop.html](../app/client/templates/shop.html) | 슬림 히어로, `#f4f4f4` `shop-section-band`, 탭 라벨(소개), 상품 루트·페이저 |
| [app/client/templates/review_list.html](../app/client/templates/review_list.html) | 테마 클래스(공통 style.css) |
| [app/client/templates/review_detail.html](../app/client/templates/review_detail.html) | `page--review-detail`, 상단 풀너비 CTA, 하단 fixed 도크, 동일 `data-*` |
| [static/css/style.css](../static/css/style.css) | Pretendard 스택, 토큰(`--surface-muted`, radius 4~8px), 헤더·몰·2열·3:4·랭킹 밀도·리뷰 도크 |
| [static/js/shop-tabs.js](../static/js/shop-tabs.js) | 탭 전환(URL 동기화) |
| [static/js/shop-products.js](../static/js/shop-products.js) | 전체 목록 보관, **5개/페이지** 슬라이스·페이저, 이미지 영역 구매 링크+동일 `data-*` |
| [app/admin/templates/influencers.html](../app/admin/templates/influencers.html) | 편집 링크 |
| [app/admin/templates/influencer_edit.html](../app/admin/templates/influencer_edit.html) | 신규 폼 |

## 공개 URL (라우팅)

- `/{name_slug}` 허브(상품), `/{name_slug}/review`, `/{name_slug}/review/{id}`, `/{name_slug}/introduce`.
- `/shop/...`, `/reviews/...` → 새 경로로 301.

## 검증

### 레이아웃·시각 (브라우저)

- 헤더·푸터·`main.page-body`가 모두 `.container`의 동일 `max-width`(1200px)와 `--page-pad-x`로 **가로 정렬**되는지 확인.
- 공개 페이지 전반: 배경 **화이트** 위주, 카드·탭 등 **그림자 없음**, 구분은 **1px 보더**(헤더·푸터·마키) 및 몰의 **8px `--surface-muted`(#f4f4f4) 밴드**로 확인.

### 기능·반응형

- 몰: 상품 탭에서 구매 링크에 `lptag` 유지, 클릭 시 `/api/click` POST.
- 리뷰 상세: `buy_url`로 이동, 상단·하단(fixed) CTA 모두 동일 트래킹 속성.
- 모바일(≤720px): 상품 그리드 **2열**, 썸네일 **3:4**, 한 페이지 **5개** + 페이저.
- `prefers-reduced-motion`: 마키 애니메이션 비활성.
