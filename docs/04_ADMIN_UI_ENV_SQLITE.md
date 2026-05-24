# 04 — 관리자 UI·환경 로딩·SQLite 마이그레이션

백오피스 소소한 UX와 **로컬 DB 스키마 보정**, **타입/분석기** 정리.

## `app/admin/templates/products.html` + `static/js/admin-products.js`

- **「목록 새로고침」** 버튼: 선택 채널의 등록 상품 표만 `loadRegisteredItems()` 재호출 (페이지 전체 새로고침 없음).
- `loadRegisteredItems()`는 **`Promise<boolean>`** 반환 — 수동 새로고침 성공 시에만 성공 모달.

## `main.py` — 환경 변수

- **`_load_env_file()`**: `dotenv_values`로 `.env`를 읽고, **현재 `os.environ` 값이 비어 있을 때만** 키를 채움.  
  → 셸/IDE에 빈 `CHANNEL_201_FILE_ID=`만 있어 `.env`가 무시되던 문제 완화.

## SQLite 보정·인플 시드 (스크립트)

- [`scripts/setup_sqlite_from_roster.py`](../scripts/setup_sqlite_from_roster.py): 예전 DB 스키마 보정(`reviews.product_id`, `click_logs`·`influencers` 컬럼 등) + `Base.metadata.create_all` + 로스터 기준 `influencers` 시드. 배포·로컬에서 예전 `database.db`를 쓸 때 **서버 기동 전에 한 번** 실행.
- `main.py` 는 `create_all` 만 한다.

## `models.py`

- `Review.product_id`: **`Mapped[int | None]`** (`nullable=True`와 일치). `product` 관계는 `Product | None`.

## `main.py` — `get_db`

- 반환 타입 **`Generator[Session, None, None]`** (`yield`와 Pyright 일치).

## 클릭 로그 (`/admin/logs`)

- `click_logs`에 아래 스냅샷 컬럼이 추가되며, 서버 기동 시 `main.py`의 `_ensure_click_log_schema()`가 구버전 DB를 보정한다.
  - `client_user_agent` (`VARCHAR(512)`)
  - `page_url` (`VARCHAR(800)`)
  - `referrer_snapshot` (`VARCHAR(600)`)
- `POST /api/click`은 위 값을 선택적으로 받아 저장한다.
- `/admin/logs`는 페이지 URL·유입(referrer)·OS·브라우저를 함께 표시한다.

## 기타

- 루트 [`pyrightconfig.json`](../pyrightconfig.json): include·venv 경로 (선택).

## 연계

- 클릭 로그 API: `POST /api/click` — `product_id` 스냅샷과 함께 `client_user_agent`/`page_url`/`referrer_snapshot`을 저장한다.
