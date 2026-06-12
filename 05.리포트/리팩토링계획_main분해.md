# 리팩토링 계획 — `main.py` 신(神) 파일 분해

> 작성일: 2026-06-12 · 유형: 온디맨드 분석(05.리포트) · 대상: `main.py`(1431줄)
> 원칙: **동작 보존(behavior-preserving) 리팩토링.** 라우트 경로·응답·쿠팡/트래킹 계약을 1바이트도 바꾸지 않는다.

---

## 0. 요약

`main.py` 한 파일에 **부트스트랩 · 미들웨어 · DB 마이그레이션 · 예외 핸들러 · 공통 헬퍼 · 공개 라우트 · 어드민 HTML 라우트**가 모두 들어 있다. JSON API(`app/admin/ops/`)는 이미 잘 모듈화돼 있으므로, **같은 패턴을 main.py에도 적용**해 `app/core/`(현재 빈 패키지)와 라우터 모듈로 분리한다.

목표: `main.py` **1431줄 → 약 40줄**(앱 조립 + include_router만).

---

## 1. 현재 상태 진단

### 1.1 한 파일에 섞인 관심사 (라인 기준)

| 구획 | 위치(대략) | 내용 |
|------|-----------|------|
| 설정/부트스트랩 | 22–49, 352–358 | `_load_env_file`, `_normalize_site_base`, `FastAPI()`, `Jinja2Templates`, `app.mount` |
| import 시점 부작용 | 37, 218, 242, 260 | `_load_env_file()`, `create_all`, `_ensure_click_log_schema()`, `_ensure_influencer_v2_columns()` |
| 미들웨어 | 112–171, 202–216 | `AccessDetailLogMiddleware`, `_append_access_detail_log`, `_client_ip_from_request`, `redirect_www_to_apex` |
| DB 마이그레이션 | 221–260 | `_ensure_click_log_schema`, `_ensure_influencer_v2_columns` (부팅마다 ALTER TABLE) |
| 예외 핸들러 | 360–424 | `http_exception_handler`, `unhandled_exception_handler`, `_admin_auth_redirect_handler` + 보조 |
| 공통 헬퍼 | 263–349 | `_client_theme_context`, `_ua_os_browser`, `_ellipsis_middle`, `enrich_coupang_url_for_public` |
| DB 세션 | 427–432 | `get_db` |
| 공개 클라이언트 라우트 | 435–600, 1196–1431 | health, `/`, about, privacy, `/api/mall-products`, 레거시 301, `/api/click`, 인플 허브, 공개 리뷰 |
| 어드민 HTML 라우트 | 600–1196 | login/logout, dashboard, reviews CRUD, influencers, products, dm, sheets, logs |

### 1.2 핵심 결합(공유 전역)

분해 시 반드시 공유돼야 하는 모듈 전역:

- **`templates`** (Jinja2Templates) — 예외 핸들러 + 모든 HTML 라우트가 같은 인스턴스를 써야 함.
- **`get_db`** — 거의 모든 라우트의 `Depends`.
- **헬퍼** `_client_theme_context`, `enrich_coupang_url_for_public`, `_ua_os_browser` 등 — 라우트·핸들러 공용.
- **`engine`/`SessionLocal`** (models) — db·마이그레이션.

→ 해결: 이 공유물을 **`app/core/`** 로 내려 라우터가 `app.core.*` 에서 import 하게 한다. **라우터는 절대 `main` 을 import 하지 않는다**(순환 방지).

### 1.3 가장 큰 위험: import 시점 실행 순서

현재 main.py 최상단에서 **순서대로** 실행된다:
`_load_env_file()` → (FastAPI/라우터 import) → `create_all` → `_ensure_click_log_schema()` → `_ensure_influencer_v2_columns()`.

이 **순서가 깨지면 런타임 버그**(예: env 로드 전에 `os.environ` 읽기, create_all 전에 ALTER). 분해 후에는 main.py가 이 순서를 **명시적 함수 호출**로 보장한다.

---

## 2. 목표 모듈 구조

```
app/core/
  __init__.py
  config.py        # _load_env_file, _normalize_site_base, KST, 공개 상수
  db.py            # engine/SessionLocal 재노출, get_db, run_migrations()
  templates.py     # templates = Jinja2Templates([client, admin])  (앱 비의존)
  helpers.py       # _ua_os_browser, _ellipsis_middle, enrich_coupang_url_for_public, _client_ip_from_request
  theme.py         # _client_theme_context
  access_log.py    # AccessDetailLogMiddleware, _append_access_detail_log
  errors.py        # register_error_handlers(app)  (예외 핸들러 3종 + 보조)
app/client/
  routes.py        # 공개 라우트(home/about/privacy/허브/공개리뷰/레거시301) → APIRouter
  api_routes.py    # /api/mall-products, /api/click → APIRouter
  mall_products_service.py  # mall-products 캐시(TTL)·날짜시드 셔플·httpx fetch
app/admin/
  web_routes.py    # 어드민 HTML 라우트(login~logs, reviews CRUD, influencers) → APIRouter
main.py            # ≈40줄: 앱 생성 → env/migration → 미들웨어/핸들러 등록 → include_router
```

> 명명 주의: 어드민 HTML 라우트는 `app/admin/web_routes.py` 로 둔다(기존 `app/admin/ops/routes/` JSON API와 구분). `app/admin/auth.py` 와 충돌 없음.

### 2.1 import 의존 순서(순환 없음)

```
config → db → templates → helpers → theme
                                   ↘ client/routes, client/api_routes, admin/web_routes  (core.* + services import)
errors(app 주입) · access_log(독립)
main.py → 위 전부를 조립
```

라우터는 `core.templates`, `core.db.get_db`, `core.helpers`, `core.theme` 만 의존. `errors.py` 는 `register_error_handlers(app)` 팩토리로 app을 주입받아 핸들러 등록(전역 templates는 core에서 공유).

---

## 3. 단계별 실행 계획 (작은 안전 슬라이스)

각 단계는 **독립 머지 가능 + 스모크 통과**가 조건. 매 단계 후:

```bash
python3 -m unittest tests.test_smoke -v      # 앱 로드 + 핵심 엔드포인트
python3 -c "import main"                       # import 부작용·순서 확인
```

### Phase 0 — 안전망 확정
- [ ] `tests/test_smoke.py` 가 커버하는 경로 확인(health, `/admin/api/ops/channels`, 홈). 부족하면 `/`, `/about`, `/admin/login`(302/200), `/api/mall-products` 최소 assert 추가.
- [ ] 현재 라우트 목록 스냅샷 저장: `app.routes` 의 (path, methods) 목록을 파일로 덤프 → 분해 후 **diff 0** 을 합격 기준으로.

### Phase 1 — 무결합 코어 추출 (위험 최저)
- `core/config.py` ← `_load_env_file`, `_normalize_site_base`, `KST`, 공개 상수(`_DEFAULT_COUPANG_IMAGE_WORKER` 등)
- `core/templates.py` ← `templates`
- `core/db.py` ← `get_db`, `run_migrations()`(= `create_all` + `_ensure_click_log_schema` + `_ensure_influencer_v2_columns` 통합)
- main.py: 위를 import하고, 최상단에서 `config.load_env()` → `run_migrations()` **순서 유지**.
- 검증: import·스모크.

### Phase 2 — 공통 헬퍼 추출
- `core/helpers.py` ← `_ua_os_browser`, `_ellipsis_middle`, `enrich_coupang_url_for_public`, `_client_ip_from_request`
- `core/theme.py` ← `_client_theme_context`
- main.py 내 참조를 import로 교체. **로직 변경 금지**(특히 `enrich_coupang_url_for_public` = JS `withCoupangPartnerQuery` 계약).

### Phase 3 — 미들웨어 · 예외 핸들러 추출
- `core/access_log.py` ← `AccessDetailLogMiddleware`, `_append_access_detail_log`
- `core/errors.py` ← 예외 핸들러 3종 + `_request_wants_json_error`/`_friendly_404_message` 등 → `register_error_handlers(app)`
- main.py: `app.add_middleware(...)`, `register_error_handlers(app)`, `redirect_www_to_apex`(미들웨어)만 남김.

### Phase 4 — 공개 라우트 추출
- `app/client/mall_products_service.py` ← `/api/mall-products` 내부 캐시/셔플/fetch(main.py 487–577)
- `app/client/routes.py` ← health, `/`, about, privacy, 레거시 301(`/shop/...`, `/reviews/...`), 인플 허브(`/{name_slug}`, `/review`, `/introduce`, `/review/{id}`) + `_influencer_hub_page`, `_public_slug_is_reserved`
- `app/client/api_routes.py` ← `/api/mall-products`, `/api/click`
- main.py: `app.include_router(client_router)` 등 추가.
- 주의: `/{name_slug}` 류 **catch-all 라우트는 등록 순서상 맨 마지막**이어야 함(현재도 파일 끝). include 순서로 보장.

### Phase 5 — 어드민 HTML 라우트 추출
- `app/admin/web_routes.py` ← login/logout, dashboard(+`_fetch_channel_product_count`, `_total_sheet_products_count`), reviews CRUD(+`_parse_optional_product_id`, `_review_sheet_fields_from_form`, `_log_review_admin_persist`), influencers(+edit), products, dm, sheets, logs
- main.py: `app.include_router(admin_web_router)`.

### Phase 6 — main.py 최종 정리
- main.py = 앱 생성 → `load_env`/`run_migrations` → 미들웨어·핸들러 등록 → `include_router`(ops, ig_webhook, client, client_api, admin_web) → 끝. (≈40줄)
- 전체 스모크 + Phase 0 라우트 스냅샷 **diff 0** + 수동 점검(홈/몰/어드민 1회).

---

## 4. 합격 기준 (매 단계 공통)

1. `python3 -c "import main"` 부작용·순서 정상(env→migration).
2. `tests.test_smoke` 통과.
3. `app.routes` (path, methods) 스냅샷 **diff 0**.
4. 쿠팡 딥링크/lptag·트래킹 `data-*` 동작 불변(Phase 2·4 특히).

---

## 5. 건드리지 않는 것 (범위 밖)

- **프런트 JS**: `static/js/shop-products.js`, `tracking.js` — 문서화된 **쿠팡·트래킹 불변 계약**. 이번 리팩토링 대상 아님.
- **`app/admin/ops/`** — 이미 모듈화돼 있어 그대로 둔다.
- **DB 스키마·라우트 경로·응답 포맷** — 변경 금지(순수 구조 이동).

---

## 6. 롤백·안전

- 각 Phase = 1 커밋(또는 1 PR). 문제 시 해당 커밋만 되돌림.
- Phase 간 의존이 단방향(core ← routes ← main)이라 부분 롤백 안전.
- import 순서 회귀가 가장 흔한 사고 → Phase 1에서 `run_migrations()` 호출 위치를 명시 주석으로 고정.

---

## 7. 작업 체크리스트

- [ ] Phase 0: 스모크 보강 + 라우트 스냅샷
- [ ] Phase 1: core/config·templates·db
- [ ] Phase 2: core/helpers·theme
- [ ] Phase 3: core/access_log·errors
- [ ] Phase 4: client/routes·api_routes·mall_products_service
- [ ] Phase 5: admin/web_routes
- [ ] Phase 6: main.py 최종 축소 + 전체 검증
