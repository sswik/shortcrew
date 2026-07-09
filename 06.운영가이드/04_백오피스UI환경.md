# 04 — 관리자 UI·환경 로딩·DB 스키마

백오피스 UX, **DB 스키마 생성(MySQL)**, 타입/분석기, **ShortCrew V2 admin 테마** 정리.

## ShortCrew V2 — Admin Tailwind

- [_admin_tailwind_config.html](../app/admin/templates/_admin_tailwind_config.html): **시안 primary** (`#00C2D1` 기준 50–900), 다크 차콜 surface·앰버 보조 — 클라이언트 V2와 색감 통일
- [layout.html](../app/admin/templates/layout.html), [login.html](../app/admin/templates/login.html): 인라인 `tailwind.config` 제거 → `{% include "_admin_tailwind_config.html" %}`
- favicon: `/static/images/brand/logo.png`

## 인플루언서 편집 (`influencer_edit.html`)

- `profile_meta_json` — MBTI·카테고리·팬덤명 등 (JSON 객체, 서버 `validate_profile_meta_json`)
- `mall_theme_json` — HEX 키 (`background`, `card`, `accent`, `textMain`, `textSub`, `border`, …). 비우면 공개 몰 fallback
- POST [main.py](../main.py) `admin_influencer_edit_post`

## Influencer V2 컬럼

- 스키마는 MySQL 에서 `Base.metadata.create_all`(앱 부팅 `run_migrations()`)로 생성된다 — `profile_meta_json`, `mall_theme_json` 포함.
- [scripts/seed_influencers_from_roster.py](../scripts/seed_influencers_from_roster.py): 로스터 기준 `influencers` 시드(채널 추가 시 실행).

> 과거 SQLite 의 `ALTER TABLE` 경량 보정(`_ensure_influencer_v2_columns` 등)은 MySQL 전환으로 제거됨.

---

## `products.html` + `admin-products.js`

- **「목록 새로고침」**: 선택 채널 등록 상품 표만 `loadRegisteredItems()` 재호출
- `loadRegisteredItems()` → `Promise<boolean>`

## `main.py` — 환경 변수

- **`_load_env_file()`**: `dotenv_values`로 `.env` 읽기. **현재 `os.environ` 값이 비어 있을 때만** 채움

## `models.py`

- `Review.product_id`: `Mapped[int | None]` (`nullable=True`)

## `main.py` — `get_db`

- 반환 타입 **`Generator[Session, None, None]`**

## 클릭 로그 (`/admin/logs`)

- `click_logs` 스냅샷: `client_user_agent`, `page_url`, `referrer_snapshot` — `_ensure_click_log_schema()`
- `POST /api/click` 저장, `/admin/logs` 표시

## 기타

- [pyrightconfig.json](../pyrightconfig.json): include·venv (선택)

## 연계

- 공개 UI V2: [05_클라이언트UI.md](05_클라이언트UI.md), [05_클라이언트UI.md](05_클라이언트UI.md)
- 클릭 API: `POST /api/click`
