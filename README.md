# 숏크루 (Shortcrew)

**숏크루** V2는 인플루언서별 개별 HTML을 만들지 않고, 슬러그 기반 라우팅으로 상품/리뷰를 동적으로 제공하는 FastAPI 서버입니다. 레포·도메인 식별자는 `shortcrew`입니다.

## 핵심 스택

- FastAPI
- SQLAlchemy + MySQL(`mysql-server:3306`, DB `crews`)
- Jinja2 Templates
- 정적 자산(`static/`) + ShortCrew V2 테마 (다크 `#121212`, 시안 `#00C2D1`, 앰버 CTA `#FFB800`)
- Docker + Cloudflare Tunnel

## 현재 구조

```text
shortcrew/
├── main.py                 # 앱 진입점, .env 로드, 라우트·템플릿 경로
├── models.py
├── .gitignore
├── .env.example             # 환경 변수 키 목록(값 비움). → .env 로 복사 후 사용
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── PRD.md / .progress.md / CLAUDE.md   # AP-Framework 문서체계 (개요·진행·규칙)
├── 00.통합자료실/ … 05.리포트/          # 산출물 문서체인 (관리·기획·구현·검수·리포트)
├── 06.운영가이드/            # 운영 상세 가이드 (채널/시트/쇼츠/인스타 DM/브리지)
├── n8n/                    # n8n 워크플로우 템플릿
├── prompts/                # Claude Code 프롬프트 라이브러리
├── tests/                  # 플랜 7단계 스모크 (test_smoke.py)
├── static/                 # 공통 CSS/JS/이미지 (`js/admin-products.js` — 상품 관리 콘솔)
│   ├── css/style.css
│   ├── js/tracking.js
│   └── images/influencers/
├── app/
│   ├── client/templates/   # 쇼핑·리뷰 공개 페이지 (home, shop, review_*)
│   └── admin/
│       ├── templates/      # 백오피스 HTML (layout, login, dashboard, products, …)
│       ├── auth.py
│       └── ops/            # /admin/api/ops JSON API·채널·시트 연동
└── sample/                 # 레퍼런스(족보). 런타임에서 import 하지 않음
```

Jinja2는 `main.py`에서 `app/client/templates`와 `app/admin/templates` 두 디렉터리를 함께 등록한다. 동일 파일명은 앞에 온 디렉터리가 우선한다.

## 실행

```bash
docker compose up -d --build
curl http://127.0.0.1:8028/health
```

같은 디렉터리에 **`google-key.json`** 이 있어야 볼륨 마운트가 성공한다. DB 는 외부 MySQL(`mysql-server:3306`, DB `crews`, `ejlab_global_net`)에 접속하며 `.env` 의 `DATABASE_URL` 로 지정한다.

### Cloudflare Tunnel로 공개

1. [Cloudflare Zero Trust](https://one.dash.cloudflare.com/)에서 Tunnel을 만들고 **토큰**을 발급한다.
2. Zero Trust에서 **Public Hostname**은 방문자용 도메인(예: `shortcrew.co.kr`)으로 두고, **백엔드(Service / 오리진)** 는 `docker-compose.yml` 이 `127.0.0.1:8028` 에 앱을 올려 두므로 **`http://127.0.0.1:8028`**(또는 `http://localhost:8028`)으로 둔다. `cloudflared` 는 **`network_mode: host`** 로 호스트에 바인된 그 포트에 붙는다(브리지 전용 컨테이너였다면 오리진의 `127.0.0.1` 이 앱이 아니어서 502가 난다).
3. 루트 `.env`에 `CLOUDFLARE_TUNNEL_TOKEN=` 토큰 값을 넣는다(저장소에 커밋하지 않는다).
4. 실행:

```bash
docker compose --profile tunnel up -d --build
```

토큰이 유출된 적이 있으면 Zero Trust에서 터널 토큰을 **재발급**하고, 이전 토큰은 폐기한다.

또는 로컬 파이썬:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8028
```

## 환경 변수 (플랜 6단계)

1. 루트에서 `cp .env.example .env`
2. [.env.example](.env.example)에 나열된 키만 채운다(실제 비밀·키는 커밋하지 않음).
3. 구글 시트 API는 **루트 `google-key.json`**(서비스 계정 JSON)이 있어야 한다. `GOOGLE_SERVICE_ACCOUNT_JSON` 은 `/admin/sheets` 화면 표시용으로만 쓰인다.

백오피스·채널·Ops API 키 설명은 `.env.example` 주석과 아래「백오피스 인증」·[06.운영가이드/01_채널추가가이드.md](06.운영가이드/01_채널추가가이드.md)를 병행하면 된다.

## 통합 스모크 (플랜 7단계)

의존성 설치 후 앱 로드·핵심 엔드포인트만 빠르게 확인한다.

```bash
source .venv/bin/activate   # 또는 해당 venv
python3 -m unittest tests.test_smoke -v
```

`ADMIN_PASSWORD`가 비어 있으면 `/admin/api/ops/channels`가 200으로 내려오고, 설정되어 있으면 로그인으로 302인지 검사한다. 브라우저로 5메뉴·시트 UI까지 보는 수동 검증은 플랜 6절과 병행하면 된다.

## 주요 URL

### 공개

- `/` 인플루언서 홈
- `/{name_slug}` 인플 독립몰 허브(상품 탭 기본). `/{name_slug}/review`, `/{name_slug}/introduce`는 각 탭 URL. **상품 목록은 DB가 아니라** 브라우저가 Apps Script 웹앱에서 **GET**한 JSON(우선 `CHANNEL_*_MALL_PRODUCTS_API_URL`, 비우면 `CHANNEL_*_PRODUCT_DELIVERY_WEBAPP_URL`과 동일 URL로 폴백). 썸네일은 **전역** `COUPANG_IMAGE_WORKER_BASE`(비우면 `https://image.shortcrew.co.kr/`)
- `/{name_slug}/review/{review_id}` 리뷰 상세
- 레거시 `/shop/...`, `/reviews/...` 는 새 경로로 **301** 리다이렉트
- `POST /api/click` 클릭 로그

### 클릭 로그 메모

- `/api/click`은 `influencer_slug`, `product_id` 외에 아래 접속 스냅샷을 함께 저장한다.
  - `client_user_agent` (최대 512)
  - `page_url` (최대 800)
  - `referrer_snapshot` (최대 600)
- `/admin/logs`에서 시각·인플루언서·페이지 URL·유입(referrer)·OS·브라우저·상품명을 확인할 수 있다.

### 백오피스 인증 (`.env`)

- `ADMIN_PASSWORD`: 설정 시 `/admin` 보호. 미설정이면 로컬에서 무인증(개발용).
- `ADMIN_EMAIL`: 설정 시 로그인 화면에서 **이메일·비밀번호 둘 다** 검사(대소문자 무시). 비우면 기존처럼 비밀번호만 검사.

### 백오피스 (HTML)

- `/admin/login`, `POST /admin/login`, `POST /admin/logout`
- `/admin/dashboard` 대시보드
- `/admin/products` 상품 관리(쿠팡 검색·시트 전송·등록 상품; JS는 `static/js/admin-products.js`)
- `/admin/reviews` 리뷰 목록·필터
- `/admin/reviews/new` 새 리뷰(Toast UI Editor)
- `/admin/reviews/{id}` 관리자 상세(Toast UI Viewer)
- `/admin/reviews/{id}/edit` 수정
- `/admin/influencers` 인플루언서별 집계
- `/admin/sheets` 시트·연동 안내
- `/admin/logs` 클릭 로그 조회

### 운영 JSON API

- 마운트 prefix: `/admin/api/ops` (예: `GET /admin/api/ops/channels`)
- 채널 추가 절차: [06.운영가이드/01_채널추가가이드.md](06.운영가이드/01_채널추가가이드.md)

## 문서 / 산출물

- 개요·목표·산출물 인덱스: [PRD.md](PRD.md) · 진행 추적: [.progress.md](.progress.md) · 작업 규칙: [CLAUDE.md](CLAUDE.md)
- 운영 상세 가이드(`06.운영가이드/`): [채널추가](06.운영가이드/01_채널추가가이드.md) · [시트딥링크](06.운영가이드/02_시트딥링크미리보기.md) · [공개몰·파트너스](06.운영가이드/03_공개몰파트너스링크.md) · [백오피스UI·env](06.운영가이드/04_백오피스UI환경SQLite.md) · [클라이언트UI](06.운영가이드/05_클라이언트UI.md) · [쇼츠시트리뷰자동화](06.운영가이드/06_쇼츠시트리뷰자동화.md) · [쇼츠자동화진단](06.운영가이드/07_쇼츠자동화진단교정.md) · [인스타댓글→DM](06.운영가이드/08_인스타댓글자동DM.md) · [쇼츠-커머스 브리지 설계](06.운영가이드/09_쇼츠커머스브리지설계.md)

## 딥링크 정책 메모

- 쿠팡 딥링크 API 요청의 `subId`는 고정값 `shortcrew`를 사용한다.
- 시트 미리보기/전송 흐름에서 `subId` 표시·병합은 제거되었다.
- 공개 몰 링크 보강은 `lptag`만 적용한다(`subid` 쿼리 미부착).
