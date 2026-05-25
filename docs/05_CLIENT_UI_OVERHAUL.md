# 클라이언트 UI — ShortCrew V2.0

> **현행 체크리스트·Phase 게이트:** [08_CLIENT_UI_REBRAND.md](08_CLIENT_UI_REBRAND.md)  
> **기준 PDF:** [00_Manual_CLIENT_UI_Change.pdf](00_Manual_CLIENT_UI_Change.pdf)

## 목표

- 시각: **모바일 퍼스트** 팬덤·쇼핑 UX — **Pretendard**, 다크 차콜 `#121212`, 시안 `#00C2D1`, 앰버 CTA `#FFB800`, 슬림 스티키 헤더 **52px**, 홈 **2열 큐카드**, 상품 **2열·1:1** 썸네일, **5개/페이지**, 상품명 **검색**
- 기술: 단일 [static/css/style.css](../static/css/style.css) + [app/client/templates](../app/client/templates). 테마 엔진 [app/client/mall_theme.py](../app/client/mall_theme.py)
- 관리자: Tailwind + [_admin_tailwind_config.html](../app/admin/templates/_admin_tailwind_config.html) (시안 primary)
- **절대 보존:** [tracking.js](../static/js/tracking.js), [shop-products.js](../static/js/shop-products.js)의 쿠팡·트래킹 계약 (페이지당 5개·검색만 확장)

## 트래킹·URL

1. **시트 상품:** `data-product-id` = VP/ctag 추출 문자열. `/api/click` 정수 파싱 (DB id와 불일치 가능 — 레거시 유지)
2. **일기장 상세:** `buy_url` 서버 보강만. 상단 인라인 + 하단 fixed 도크 **동일 `data-*`**, CTA **amber**

## 데이터 모델 (`Influencer`)

| 필드 | 설명 |
|------|------|
| `bio`, `youtube_url`, `instagram_url`, `tiktok_url`, `cover_image` | 프로필·몰 히어로 |
| `profile_meta_json` | MBTI, category, fandom_name 등 (단일 JSON) |
| `mall_theme_json` | per-mall HEX 테마 (비우면 V2 fallback) |

마이그레이션: `main.py` `_ensure_influencer_v2_columns()`, [setup_sqlite_from_roster.py](../scripts/setup_sqlite_from_roster.py)

## 수정 파일 (V2)

| 파일 | 내용 |
|------|------|
| [models.py](../models.py) | `profile_meta_json`, `mall_theme_json` |
| [mall_theme.py](../app/client/mall_theme.py) | 파싱·CSS vars |
| [main.py](../main.py) | 컨텍스트·admin POST·301 유지 |
| [base.html](../app/client/templates/base.html) | V2 로고·테마 vars |
| [home.html](../app/client/templates/home.html) | 큐카드 2열 덱 |
| [shop.html](../app/client/templates/shop.html) | 검색·일기장 탭·테마 |
| [review_detail.html](../app/client/templates/review_detail.html) | amber CTA |
| [style.css](../static/css/style.css) | V2 `:root` |
| [shop-products.js](../static/js/shop-products.js) | 5개/페이지·검색 |
| [influencer_edit.html](../app/admin/templates/influencer_edit.html) | JSON 편집 |

## CSS 토큰

`--bg-base`, `--surface-card`, `--cyan-main`, `--amber-cta`, `--text-main`, `--text-muted`, `--border-line` — 상세는 [08](08_CLIENT_UI_REBRAND.md#css-토큰-v2).

## 검증

- 헤더·푸터·`main.page-body` 동일 `max-width` 1240px, `--page-pad-x`
- 다크 배경, 카드 그림자 없음, `shop-section-band` 8px
- 모바일 ≤720px: 상품 2열, 5개 페이징
- `prefers-reduced-motion`: 마키 off

## 상품 전시 순서 랜덤화

- `/api/mall-products` 프록시 응답 시 **날짜 시드(`date.today()`) 기반 셔플** 적용
- `random.Random(str(date.today())).shuffle(items)` — 같은 날에는 모든 사용자에게 동일 순서, 자정(KST) 넘으면 자동 변경
- 캐시(45s TTL)에 셔플된 결과를 저장하므로 캐시 히트 시에도 순서 일관
- 구현 위치: [main.py](../main.py) `api_mall_products()`

## 공개 URL

- `/{name_slug}`, `/{name_slug}/review`, `/{name_slug}/review/{id}`, `/{name_slug}/introduce`
- `/shop/…`, `/reviews/…` → 301
