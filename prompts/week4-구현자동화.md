# Week 4 프롬프트: 구현 자동화

## P-401. 프론트엔드 코드 생성기

```
claude "화면설계서.md와 디자인스타일가이드.md를 읽고 Next.js + Tailwind CSS로 프론트엔드 코드를 생성해줘.
- 각 화면을 별도 페이지 컴포넌트로 만들어줘
- Vercel Root Directory는 src/frontend/
- useSearchParams 사용 시 반드시 <Suspense>로 래핑
- API 호출은 /api/ 프록시 경로 사용
- next.config.js: images.unoptimized = true"
```

**입력**: 02.기획문서/화면설계서.md, 03.구현문서/디자인스타일가이드.md
**출력**: src/frontend/ (Next.js 프로젝트)
**참고**: 화면설계서의 레이아웃, 컴포넌트, 인터랙션 명세를 코드로 변환합니다. Figma 디자인이 있다면 색상, 간격 등 디자인 스펙을 텍스트로 전달하여 반영합니다.

**실전 주의사항**:
- `useSearchParams()`는 반드시 `<Suspense>` 래핑 필수 (Next.js 14+ prerender 에러 방지)
- `output: 'export'` 설정은 동적 라우트(`[id]`)와 충돌하므로 사용하지 않음
- API URL은 환경변수 `NEXT_PUBLIC_API_URL`로 관리

---

## P-402. 백엔드 API 생성기

```
claude "API스펙.md를 읽고 Express.js REST API를 생성해줘.
- 각 엔드포인트별 라우터, 컨트롤러, 미들웨어를 만들어줘
- DB 연결: Supabase REST API (run_query/run_mutation RPC 함수)
- 인증: bcryptjs (네이티브 bcrypt 불가, 서버리스 환경)
- Body Parser: Vercel '!' escaping 이슈 대응용 커스텀 파서 포함"
```

**입력**: 02.기획문서/API스펙.md
**출력**: src/backend/ (Express.js 프로젝트)
**참고**: API 스펙의 엔드포인트, 파라미터, 응답 형식을 그대로 구현합니다.

**실전 주의사항**:
- Supabase IPv6 전용 → Vercel Lambda(IPv4)에서 직접 PG 연결 불가 → REST API의 RPC 함수 사용
- `bcrypt` 네이티브 모듈은 서버리스에서 node-pre-gyp 에러 → `bcryptjs` 사용
- Vercel Body Escaping: `!` 포함 입력 시 JSON 파싱 에러 → 커스텀 바디 파서로 invalid escape 제거

---

## P-403. 코드 리뷰 요청기

```
claude "이 PR의 코드를 보안/성능/품질 관점에서 리뷰해줘. 개선 사항을 구체적으로 제안해줘"
```

**입력**: Git diff 또는 PR 내용
**출력**: 리뷰 코멘트
**참고**: GitHub PR 생성 후 Claude Code로 리뷰를 수행합니다

---

## P-404. DB 스키마 생성기

```
claude "기능명세서.md의 데이터 모델을 기반으로 PostgreSQL 스키마를 설계해줘. ERD를 Mermaid로 그리고, SQL DDL도 생성해줘"
```

**입력**: 02.기획문서/기능명세서.md
**출력**: DB 스키마 (ERD + DDL)
**참고**: 교육에서는 설계까지만 수행하며, 실제 DB 구축은 선택 사항입니다

---

## P-405. 디자인 스타일 가이드 생성기

```
claude "서비스기획서.md의 브랜드 전략과 화면설계서.md를 기반으로 디자인 스타일 가이드를 작성해줘. 컬러 시스템, 타이포그래피, 레이아웃, UI 컴포넌트, 인터랙션 규칙을 포함해줘"
```

**입력**: 02.기획문서/서비스기획서.md, 02.기획문서/화면설계서.md
**출력**: 03.구현문서/디자인스타일가이드.md
**참고**: 프론트엔드 코드 생성 시 이 가이드의 컬러/폰트/컴포넌트 스펙을 참조합니다. Figma Make 프롬프트로도 활용 가능합니다.

---

## P-406. Vercel 배포 설정

```
claude "Vercel에 배포할 수 있도록 프로젝트를 설정해줘.
- Root Directory: src/frontend/
- API 프록시: pages/api/[...path].ts -> Express 백엔드
- 환경변수: SUPABASE_URL, SUPABASE_KEY, JWT_SECRET, DATABASE_URL
- Body Parser: Vercel의 '!' escaping 문제 해결용 커스텀 파서
- bcryptjs 사용 (bcrypt 네이티브 모듈 불가)
- next.config.js: images.unoptimized = true
- vercel.json 생성"
```

**입력**: src/frontend/, src/backend/ 소스 코드
**출력**: vercel.json, pages/api/[...path].ts, 환경변수 가이드
**참고**: Vercel 서버리스 환경에 Express 백엔드를 프록시하는 구성입니다.

**실전 주의사항**:
- `pages/api/[...path].ts`에서 Express app을 import하여 모든 API 요청을 프록시
- 환경변수는 Vercel 대시보드 > Settings > Environment Variables에 등록
- `.vercelignore`로 한글 디렉토리 제외 (ENAMETOOLONG 방지)
- 배포 후 반드시 라이브 사이트에서 수동 검증 수행

---

## P-407. 결제 연동 (토스페이먼츠)

```
claude "토스페이먼츠 결제를 연동해줘.
- SDK: @tosspayments/tosspayments-sdk
- 흐름: 장바구니 -> pending 주문 생성 -> PG 결제창 -> /api/payments/confirm -> paid 전환
- .AP-key.md에서 클라이언트 키, 시크릿 키 읽기
- 금액 검증: KRW zero-decimal (89000 = 89,000원)
- 멱등성: 이미 paid인 주문에 confirm 재호출 시 스킵
- 프론트: checkout/page.tsx, payments/success/page.tsx, payments/fail/page.tsx
- 백엔드: paymentController.confirmPayment (Toss API 호출 + DB 업데이트)"
```

**입력**: 02.기획문서/기능명세서.md (결제 관련 기능), .AP-key.md (PG사 키)
**출력**: 결제 프론트엔드 페이지 3개, 결제 백엔드 컨트롤러, DB 마이그레이션
**참고**: 한국 서비스는 토스페이먼츠 권장 (Stripe는 한국 사업자 미지원).

**실전 주의사항**:
- DB 마이그레이션: orders 테이블에 `payment_key` 컬럼 + `pending` 상태 추가
- KRW는 zero-decimal (89000 = 89,000원, 100 곱하지 않음)
- 테스트 키로 개발 → 라이브 키로 전환 시 환경변수만 교체
- confirm API에서 Toss API 호출 전 금액 검증 필수

---

## P-408. Supabase Storage 연동

```
claude "Supabase Storage를 연동해줘.
- 비공개 버킷: 인증된 사용자만 다운로드 가능한 파일 저장
- 공개 버킷: 이미지 등 공개 에셋 저장
- 파일 업로드: Supabase Storage REST API + service_role JWT
- Signed URL: 시간 제한 다운로드 링크 생성
- 다운로드 관리: 횟수 제한, 권한 검증"
```

**입력**: 02.기획문서/기능명세서.md (파일 관리 기능)
**출력**: Storage 서비스 모듈, 다운로드 API 엔드포인트
**참고**: Supabase Storage는 S3 호환 API를 제공합니다. 비공개 파일은 Signed URL로 제어합니다.

**실전 주의사항**:
- service_role JWT는 백엔드에서만 사용 (프론트 노출 금지)
- Signed URL TTL은 5분 권장 (너무 길면 보안 위험)
- 파일 키 규칙 통일: `{카테고리}/{id}.{확장자}` (예: `vol/32.pdf`)
- 대용량 파일은 multipart upload 고려

---

## P-409. Group B 병렬 실행 (화면설계서 + API스펙 이후)

> V0.3 신규. 화면설계서(#9)와 API스펙(#7) 완료 후 독립적인 3개 산출물을 동시 생성합니다.

```
"화면설계서(#9)와 API스펙(#7)이 완료되었으니, 다음 3개 산출물을 병렬로 생성해줘.

1. 인프라아키텍처 (#10): 화면설계서.md + 시스템 환경 기반
2. 데이터베이스설계서 (#12): 기능명세서.md + API스펙.md 기반 ERD + DDL
3. 디자인스타일가이드 (#13): 서비스기획서.md 브랜드 전략 + 화면설계서.md 기반

각 산출물은 독립적으로 생성하되, 해당 전제 문서를 참조해.
완료 후 .progress.md를 일괄 업데이트해줘."
```

**입력**: #4, #6, #7, #9 산출물
**출력**: #10, #12, #13 (3개 산출물 동시 생성)
**전제조건**: .progress.md에서 #7, #9 상태=완료 확인
**실행 방식**: Claude Code Task 도구로 3개 서브에이전트 병렬 실행
