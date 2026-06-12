# Week 1 프롬프트: 프로젝트 초기화

> V0.3 신규, V0.41 NLM 양방향 동기화, V0.42 표준 기술 스택 기본값 확정. 프로젝트 시작 시 1회 실행하여 루트 레벨에 작업 환경을 구성합니다.
> AP-Framework 폴더는 읽기 전용 템플릿으로 유지됩니다.
>
> **V0.42 표준 기술 스택**: `Next.js + Tailwind CSS / Express.js / PostgreSQL / Vercel`
> 모든 PRD와 산출물은 이 스택을 기본값으로 작성합니다.

---

## P-101. 프로젝트 초기화 (Project Scaffold)

```
"AP-Framework-V0.42 폴더를 참조하여 프로젝트를 초기화해줘.

1. 프로젝트 루트에 다음 폴더/파일을 생성해줘:
   - 00.통합자료실/ (하위 5개 폴더 + README.md 복사)
   - 01.관리문서/ (5개 템플릿 복사: 착수보고서, WBS, 주간보고서, 중간보고서, 완료보고서)
   - 02.기획문서/ (7개 템플릿 복사: 마켓리서치~화면설계서)
   - 03.구현문서/ (4개 템플릿 복사: 인프라아키텍처~디자인스타일가이드)
   - 04.검수문서/ (2개 템플릿 복사: 테스트시나리오, 테스트결과보고서)
   - 05.리포트/ (빈 폴더 + .gitkeep)
   - src/ (frontend/, backend/ + .gitkeep)
   - tests/ (backend/ + jest.config.js, helpers.js, setup.js 복사)
   - n8n/ (워크플로우 JSON 5개 + README.md 복사)
   - .github/ (workflows/ci.yml, ISSUE_TEMPLATE/ 복사)
2. CLAUDE.template.md를 기반으로 프로젝트 루트에 CLAUDE.md를 생성해줘
3. PRD.template.md를 기반으로 프로젝트 루트에 PRD.md를 생성해줘
4. .AP-key.template.md를 기반으로 프로젝트 루트에 .AP-key.md를 생성해줘
5. .progress.md를 프로젝트 루트에 복사해줘
6. .gitignore를 프로젝트 루트에 복사해줘

주의사항:
- AP-Framework-V0.42/ 폴더 내용은 수정하지 마세요 (읽기 전용 템플릿)
- 이미 루트에 동일 파일이 있으면 덮어쓰지 마세요"
```

**입력**: AP-Framework-V0.42/ (템플릿 폴더)
**출력**: 프로젝트 루트에 전체 폴더 구조 생성
**참고**: 이 프롬프트는 프로젝트 시작 시 1회만 실행합니다

---

## P-102. PRD.md 작성 (Product Requirements Document)

```
"PRD.md에 프로젝트 요구사항을 작성해줘.

다음 항목을 채워줘:
- 프로젝트명, 고객사/조직, 팀 규모, 기간, 예산
- 기술 스택: 'Next.js + Tailwind CSS / Express.js / PostgreSQL / Vercel' (V0.42 표준 스택 기본값)
- 프로젝트 목표 (2-3문장)
- 핵심 기능 (3-5개)
- 대상 사용자
- 비기능 요건

작성 후 .progress.md의 'PRD.md 프로젝트 개요 작성' 상태를 '완료'로 업데이트해줘.

참고: 프로젝트 특성상 기본 스택을 변경해야 하는 경우에만 다른 스택을 명시하세요. 기본값 유지 시 W4 구현 자동화에서 일관된 코드 생성 결과를 받을 수 있습니다."
```

**입력**: 사용자 구두 설명, 아이디어, 또는 RFP (00.통합자료실/고객자료/)
**출력**: PRD.md (프로젝트 요구사항 기입 완료)
**전제조건**: P-101 완료 (프로젝트 초기화)

---

## P-103. 통합자료실 셋업 + NotebookLM 연동

```
"00.통합자료실/에 프로젝트 참조 자료를 정리해줘.

1. 고객자료/: 사용자가 제공한 RFP, 사업 브리프 등을 이동/복사
2. 정책자료/: 관련 법규, 보안 정책 등을 정리
3. 참고자료/: 경쟁사/벤치마킹 자료를 웹 검색으로 수집

완료 후:
- NotebookLM에 프로젝트 노트북을 생성하고 자료를 소스로 등록해줘
- .progress.md의 '통합자료실 참조 자료 셋업' 상태를 '완료'로 업데이트해줘"
```

**입력**: 고객 제공 자료, 웹 검색 결과
**출력**: 00.통합자료실/ 정리 + NotebookLM 소스 등록
**전제조건**: P-101 완료 (프로젝트 초기화)

---

## P-104. NLM 양방향 동기화 (NotebookLM -> Local)

```
"NotebookLM의 모든 소스를 로컬 참고자료 폴더에 동기화해줘.

1. nlm source list <notebook_id>로 전체 소스 목록을 조회해줘
2. 소스를 유형별로 분류해줘:
   - web_page: WebFetch로 URL 내용 수집
   - generated_text: 로컬 프로젝트 문서를 참고자료/ 폴더에 복사
   - pdf: placeholder 파일 생성
3. 각 소스를 00.통합자료실/참고자료/NLM-XX_제목요약.md 형식으로 저장해줘
   - 파일 헤더에 원본 URL, 출처, 수집일, 소스 유형을 포함해줘
4. 웹소스가 다수(10건 이상)일 경우, 5건씩 배치를 나눠 Task 도구로 병렬 처리해줘
5. 완료 후 참고자료/README.md에 전체 소스 인덱스를 생성해줘
6. .progress.md의 'NLM 소스 로컬 동기화' 상태를 '완료'로 업데이트해줘
7. Git 커밋/푸시해줘

참고:
- <notebook_id>는 .AP-key.md에서 확인
- 403 에러가 발생한 URL은 대체 출처를 검색하여 수집
- Gemini 공유 링크 등 인증 필요 URL은 placeholder 생성"
```

**입력**: NotebookLM 노트북 소스 목록
**출력**: 00.통합자료실/참고자료/NLM-*.md 파일 + README.md 인덱스
**전제조건**: P-103 완료 (통합자료실 셋업 + NotebookLM 연동)

### 소스 유형별 처리 규칙

| 소스 유형 | 처리 | 비고 |
|-----------|------|------|
| `web_page` | WebFetch로 URL 수집 -> 마크다운 변환 | 403 시 대체 출처 검색 |
| `generated_text` | 로컬 파일 복사 (PRD.md 등) | 원본 경로 헤더에 명시 |
| `pdf` | placeholder 생성 | 소스 ID + 원본 확보 안내 |

### 배치 병렬 처리 패턴

웹소스가 10건 이상일 경우, Claude Code의 Task 도구로 5건씩 배치를 나누어 병렬 처리합니다.

```
Batch 1: NLM-01 ~ NLM-05  (Task agent 1)
Batch 2: NLM-06 ~ NLM-10  (Task agent 2)
Batch 3: NLM-11 ~ NLM-15  (Task agent 3)
...
```

각 배치 에이전트에게 WebFetch + Write 도구 사용을 지시하고, 모든 배치가 완료되면 인덱스를 생성합니다.

---

## 초기화 완료 후 프로젝트 구조

```
MyProject/                         # 프로젝트 루트
  AP-Framework-V0.42/               # 읽기 전용 (템플릿 + prompts)
  00.통합자료실/                    # 작업 복사본
    고객자료/
    정책자료/
    인프라자료/
    회의록/
    참고자료/
    README.md
  01.관리문서/
    착수보고서.md
    WBS.md
    주간보고서.md
    중간보고서.md
    완료보고서.md
  02.기획문서/
    마켓리서치.md
    서비스기획서.md
    요구사항정의서.md
    기능명세서.md
    API스펙.md
    정보구조도.md
    화면설계서.md
  03.구현문서/
    인프라아키텍처.md
    시스템정의서.md
    데이터베이스설계서.md
    디자인스타일가이드.md
  04.검수문서/
    테스트시나리오.md
    테스트결과보고서.md
  05.리포트/
  src/
    frontend/
    backend/
  tests/
    backend/
  n8n/
  .github/
  .progress.md                     # 진행 상태 추적기
  PRD.md                           # 프로젝트 요구사항 정의
  CLAUDE.md                        # 프로젝트 규칙
  .AP-key.md                       # 서비스 키
  .gitignore
```
