# Week 5 프롬프트: 검수 자동화

## P-501. 테스트 시나리오 생성기

```
claude "기능명세서.md를 읽고 테스트 시나리오를 작성해줘. 기능별 정상/예외 케이스를 포함해줘"
```

**입력**: 02.기획문서/기능명세서.md
**출력**: 04.검수문서/테스트시나리오.md
**참고**: 각 기능의 정상 흐름과 예외 케이스를 모두 포함합니다

---

## P-502. 단위 테스트 생성기

```
claude "테스트시나리오.md(TC-001~TC-060)를 기반으로 Jest 테스트 코드를 작성해줘.
- 프레임워크: Jest 29 + Supertest
- DB는 jest.mock()으로 모킹 (실제 DB 불필요)
- 파일 구조: tests/backend/ 하위에 jest.config.js, setup.js, helpers.js, *.test.js"
```

**입력**: src/backend/ 소스 코드, 04.검수문서/테스트시나리오.md
**출력**: tests/backend/ (Jest 테스트 파일 9개)
**참고**: Mock 기반 테스트로 DB 없이 CI 환경에서 안정적 실행. 92%+ Pass율 목표.

---

## P-503. CI/CD 파이프라인 생성기

```
claude "GitHub Actions CI/CD 파이프라인을 활성화해줘.
- push/PR 시 자동 실행
- Backend: npm install -> Jest 테스트 (--forceExit, continue-on-error)
- Frontend: npm install -> tsc --noEmit -> next lint
- 배포: placeholder (Vercel 등 외부 서비스 연동 시 활성화)
대상 파일: .github/workflows/ci.yml"
```

**입력**: 프로젝트 구조 (package.json, 테스트 파일 등)
**출력**: .github/workflows/ci.yml (활성화)
**참고**: AP-프레임워크의 ci.yml 템플릿 주석을 해제하고 프로젝트에 맞게 설정합니다. `npm install` 사용 (npm ci는 lock 파일 필요), Frontend는 타입 체크만 (`tsc --noEmit`), 배포는 Vercel 등 외부 서비스 권장 (GitHub Pages는 정적 전용).

**실전 주의사항**:
- `next build` 대신 `tsc --noEmit` -- 동적 라우트(`[id]`)가 있으면 `output: 'export'`와 충돌
- tests/backend/에서 Jest 실행 시 의존성(supertest, jsonwebtoken 등)을 해당 디렉토리에 직접 설치
- `--forceExit` 필수 -- 비동기 핸들러 미정리 시 Jest가 영구 대기
- `continue-on-error: true` 권장 -- Mock 불일치로 일부 TC Fail 허용

---

## P-504. 테스트 결과 보고서 생성기

```
claude "테스트 실행 결과를 분석하여 테스트결과보고서를 작성해줘. 통계, 미해결 이슈, 최종 판정을 포함해줘"
```

**입력**: 테스트 실행 결과, 04.검수문서/테스트시나리오.md
**출력**: 04.검수문서/테스트결과보고서.md
**참고**: Pass/Fail 통계와 미해결 이슈 목록을 자동으로 정리합니다

---

## P-505. 배포 후 검증 자동화

```
claude "배포된 라이브 사이트를 검증해줘.
- 대상 URL: {배포 URL}
- 검증 항목:
  1. 회원가입/로그인 (특수문자 포함 비밀번호)
  2. 정적 에셋 (이미지, 폰트 HTTP 200 확인)
  3. UI 레이아웃 (중복 요소 육안 확인)
  4. API 응답 (주요 엔드포인트 200/401 확인)
  5. 모바일 반응형 (375px 뷰포트)
  6. 환경변수 (배포 플랫폼 대시보드 확인)
- 결과를 05.리포트/배포검증결과_YYYY-MM-DD.md로 저장"
```

**입력**: 배포된 라이브 사이트 URL
**출력**: 05.리포트/배포검증결과_YYYY-MM-DD.md
**참고**: Jest 등 자동 테스트는 Mock 기반이므로 배포 환경 특이 이슈를 발견하지 못합니다. 반드시 라이브 사이트에서 수동 검증을 수행합니다.

**실전 주의사항**:
- Mock 테스트 Pass가 라이브 정상 동작을 보장하지 않음
- 배포 환경(서버리스)에서만 발생하는 문제는 디버그 엔드포인트 배포로 확인
- 6~8회 이터레이션은 정상이며, 매 실패마다 원인을 기록

---

## P-506. 온디맨드 리포트 생성기

```
claude "05.리포트/ 폴더에 {주제}에 대한 가이드 문서를 작성해줘.
- 형식: 마크다운
- 용도: 팀 내부 참고용 또는 교육 배포용
- 내용: 배경, 절차, 주의사항, 트러블슈팅을 포함"
```

**입력**: 프로젝트 컨텍스트, 주제 키워드
**출력**: 05.리포트/{주제}-가이드.md
**참고**: Document Chaining에 포함되지 않는 부가 문서를 생성합니다. 예시: 배포 가이드, 결제 연동 가이드, AI Agent 가이드 등.
