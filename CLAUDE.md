# Shortcrew — 프로젝트 규칙 (CLAUDE.md)

> AP-Framework V0.42 문서체계를 채택하되, **이 프로젝트의 실제 스택(Python/FastAPI)** 에 맞춰 조정한 규칙이다.
> 산출물 작성 전 `PRD.md` 와 `.progress.md` 를 먼저 읽고 맥락을 파악한다.

## Role
한국어로 일하는 PM 겸 엔지니어. 모든 문서 산출물은 **한국어 마크다운**으로 작성한다.

## 기술 스택 (실제 — Node 표준 아님)
- 백엔드: **FastAPI** + **SQLAlchemy + MySQL**(`mysql-server:3306`, DB `crews`). 접속은 `.env` 의 `DATABASE_URL` 필수(미설정 시 부팅 에러). SQLite 는 더는 쓰지 않는다.
- 뷰: **Jinja2** (`app/client/templates`, `app/admin/templates`)
- 정적: `static/` (CSS/JS/이미지), ShortCrew V2 테마(다크 `#121212` / 시안 `#00C2D1` / 앰버 `#FFB800`)
- 배포: **Docker + Cloudflare Tunnel** (공개 포트 `127.0.0.1:8028`)
- 외부 연동: Google Sheets(Apps Script), 쿠팡 파트너스, Instagram Graph API, 네이버 데이터랩, Google Gemini, YouTube Data API

> AP-Framework 기본 스택(Next.js/Express/PostgreSQL/jest)은 **이 프로젝트에 적용하지 않는다.**
> 코드는 `src/` 가 아니라 **루트의 `main.py`·`models.py`·`app/`** 에 있고, 테스트는 jest 가 아니라 **`tests/`(unittest/pytest)** 다.

## 작동 코드 — 변경 주의
- 작동 코드(`main.py`, `models.py`, `app/`, `static/`, `scripts/`)는 **요청 없이 임의로 바꾸지 않는다.**
- 문서·구조 작업 시에도 코드 동작은 보존한다(주석/문서 경로 갱신은 허용).
- 핵심 정책: 쿠팡 딥링크 `subId` 고정값 `shortcrew`, 공개 링크는 `lptag`만 부착, 비밀키는 `.env`/`google-key.json`(커밋 금지).

## 문서 규칙 (산출물 폴더 — 프로젝트 루트)
- 산출물은 번호 폴더에 저장한다: `01.관리문서/`, `02.기획문서/`, `03.구현문서/`, `04.검수문서/`, `05.리포트/`
- `00.통합자료실/` — 참조 자료(고객/정책/인프라/회의록/참고). UI 변경 매뉴얼 PDF 는 `참고자료/`.
- `06.운영가이드/` — **이 프로젝트 고유**의 운영 상세 가이드(채널 추가, 시트 딥링크, 쇼츠 자동화, 인스타 DM, 쇼츠-커머스 브리지 등). **코드 주석이 이 경로를 참조하므로** 파일명·위치 변경 시 코드 주석도 함께 갱신한다.
- 모든 산출물은 마크다운(.md). 이모지는 자제한다.

## 자동화 자산
- `n8n/` — n8n 워크플로우 JSON 템플릿. 비즈니스 로직은 코드(FastAPI)에 두고, n8n 은 외부 SaaS 연결·스케줄·발행 풀칠만 담당한다.
- `prompts/` — 주차별 Claude Code 프롬프트 라이브러리(참고용).
- `.github/ISSUE_TEMPLATE/` — 이슈 템플릿.
- `.AP-key.template.md` — 서비스 키 양식. 실제 값은 `.AP-key.md`(gitignore)에 채운다.

## 진행 관리
- `.progress.md` — AP-Framework 문서체인 진행 추적기. 산출물 완료 시 상태를 갱신한다.
- `PRD.md` — 프로젝트 개요·목표·핵심기능·산출물 인덱스.
