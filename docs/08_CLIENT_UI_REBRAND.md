# 08 — ShortCrew V2.0 클라이언트 UI 리브랜딩

**기준:** [Manual_CLIENT_UI_Change.pdf](Manual_CLIENT_UI_Change.pdf)  
**요약 문서:** [05_CLIENT_UI_OVERHAUL.md](05_CLIENT_UI_OVERHAUL.md) · **관리자:** [04_ADMIN_UI_ENV_SQLITE.md](04_ADMIN_UI_ENV_SQLITE.md)

## 개요

Short-on(퍼플·라이트)에서 **ShortCrew V2.0**(다크 차콜 / 시안 / 앰버)으로 전면 리브랜딩합니다. 공개 UI는 `static/css/style.css` + Jinja, per-mall 테마는 `mall_theme_json` + [app/client/mall_theme.py](../app/client/mall_theme.py).

## 불변 계약

- [static/js/tracking.js](../static/js/tracking.js): `data-track-click`, `data-influencer`, `data-product-id`
- [static/js/shop-products.js](../static/js/shop-products.js): `withCoupangPartnerQuery`, `extractCoupangProductId`, fetch/캐시/슬라이스·페이저 (변경 허용: 5개/페이지, 검색 필터)
- 레거시 301: `/shop/…`, `/reviews/…`
- 일기장 상세: 상·하단 CTA 동일 트래킹 속성

## 유의사항 — Phase별 승인 게이트

각 Phase 완료 후 **사용자 OK** 전까지 다음 Phase 코드·문서 작업을 시작하지 않습니다.

| Phase | 보고 내용 |
|-------|-----------|
| 0 | 08 MD, 에셋, README |
| 1 | DB·mall_theme.py·main 컨텍스트 |
| 2 | CSS 토큰 |
| 3 | base.html |
| 4 | 홈 큐카드 |
| 5 | 몰·shop-products.js |
| 6 | 일기장·에러 |
| 7 | admin Tailwind·편집 폼 |
| 7b | docs/05·04 개정 |
| 8 | QA |

---

## Phase 0 — 준비·에셋

- [x] `docs/08_CLIENT_UI_REBRAND.md` 생성
- [x] `static/images/brand/logo.png` (mall 로고 복사)
- [x] `README.md` V2 색상 안내
- [x] Phase 게이트 본 문서에 명시

## Phase 1 — 데이터·테마 엔진

- [x] `Influencer.profile_meta_json`, `mall_theme_json` ([models.py](../models.py))
- [x] `_ensure_influencer_v2_columns()` ([main.py](../main.py))
- [x] [app/client/mall_theme.py](../app/client/mall_theme.py)
- [x] `home` / 허브 / 일기장 상세 + admin POST 검증
- [x] [scripts/setup_sqlite_from_roster.py](../scripts/setup_sqlite_from_roster.py) 동기

## Phase 2 — CSS

- [x] `:root` V2 토큰 (`--bg-base`, `--cyan-main`, `--amber-cta`, …)
- [x] 다크 body/header, 컴포넌트 오버라이드 (PDF §7)
- [x] `shop-section-band` 8px 노출

## Phase 3 — base.html

- [x] V2 로고·메타·`mall_theme_css` 인라인

## Phase 4 — home 큐카드

- [x] 2열 그리드, bio 3줄, `profile_meta` MBTI 뱃지, amber 픽몰 CTA

## Phase 5 — 몰

- [x] 검색 `#shop-product-search`, 일기장 탭 라벨
- [x] `getPageSize()` → 5, `productsFiltered()`

## Phase 6 — 일기장·에러

- [x] amber `btn-purchase-wide`, 에러 페이지 테마 컨텍스트

## Phase 7 — Admin

- [x] `_admin_tailwind_config.html` (시안 primary)
- [x] `layout.html` / `login.html` include
- [x] `influencer_edit.html` JSON 필드

## Phase 7b — docs/05·04

- [x] [05_CLIENT_UI_OVERHAUL.md](05_CLIENT_UI_OVERHAUL.md) V2 본문
- [x] [04_ADMIN_UI_ENV_SQLITE.md](04_ADMIN_UI_ENV_SQLITE.md) V2 항목 병합

## Phase 8 — QA

- [x] `tests/test_mall_theme.py` — 테마 파싱·HEX·fallback (자동)
- [ ] 헤더·푸터·본문 `.container` 1240px 정렬 (브라우저)
- [ ] `/api/click` POST (상품·일기장 CTA)
- [ ] ≤720px 상품 2열·1:1·5개 페이징
- [ ] `mall_theme_json` 비움 → fallback
- [ ] 레거시 301 3경로
- [ ] `prefers-reduced-motion` 마키

---

## JSON 스키마

### `profile_meta_json`

```json
{ "mbti": "ENFP", "category": "스포츠", "fandom_name": "크루네임" }
```

### `mall_theme_json`

```json
{
  "background": "#121212",
  "card": "#1E1E1E",
  "accent": "#00C2D1",
  "textMain": "#FFFFFF",
  "textSub": "#A3A3A3",
  "border": "#2E2E2E",
  "cta": "#FFB800",
  "ctaHover": "#E6A600",
  "accentDark": "#0098A3"
}
```

비우면 [mall_theme.py](../app/client/mall_theme.py) `SHORTCREW_DEFAULT_THEME` 적용.

## CSS 토큰 (V2)

| 토큰 | HEX | 용도 |
|------|-----|------|
| `--bg-base` | `#121212` | 페이지 배경 |
| `--surface-card` | `#1E1E1E` | 카드·패널 |
| `--surface-muted` | `#262626` | 섹션 밴드 |
| `--cyan-main` | `#00C2D1` | Primary·탭·필 |
| `--amber-cta` | `#FFB800` | 구매 CTA |
| `--text-main` | `#FFFFFF` | 본문 |
| `--text-muted` | `#A3A3A3` | 보조 |
| `--border-line` | `#2E2E2E` | 1px 구분 |

## 완료 기준 (DoD)

- 공개 전 페이지 다크 V2 톤, 트래킹 회귀 없음
- admin primary 시안, JSON 편집 동작
- 05·04·08 문서가 코드와 일치
