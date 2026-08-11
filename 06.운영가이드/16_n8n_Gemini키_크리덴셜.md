# 16. n8n Gemini 키 — 크리덴셜 처리

n8n 워크플로우 JSON 안에 Gemini API 키가 평문으로 박혀 있던 것을 **n8n 크리덴셜**로 옮긴 기록과 방법.

## 결론 먼저: 이 n8n 에서 `$env` 는 못 쓴다

`n8n.rodimap100.com` 은 **로컬 `automation-n8n-1` 컨테이너와 다른 인스턴스**다(로컬 API 는 같은 키로 401).
그 인스턴스는 노드 내 환경변수 접근이 차단돼 있어, HTTP 노드 표현식이든 Code 노드든
`$env.X` 를 쓰면 실행이 **`access to env vars denied`** 로 죽는다. 검증 방법은 아래 "검증 레시피" 참고.

따라서 키를 빼는 수단은 **크리덴셜뿐**이고, 크리덴셜을 붙일 수 있는 건 **일반 노드뿐**이다
(Code 노드는 크리덴셜을 못 받는다).

## 적용 상태 (2026-08-12)

| 워크플로우 | 노드 | 종류 | 처리 |
| --- | --- | --- | --- |
| WF-AUTO-SCRIPT (활성) | Gemini 1차 수정 / 3차 최종 | HTTP | 크리덴셜 `Gemini API key (main)` |
| WF-댓글수집 | Gemini 답글생성 | HTTP | 크리덴셜 `Gemini API key (main)` |
| 06 전자책 | Gemini API - 전자책 콘텐츠 생성 | HTTP | 크리덴셜 `Gemini API key (ebook)` |
| WF-AUTO-SCRIPT (활성) | 발음사전 자동 업데이트 | **Code** | **평문 잔존** |
| AF05-salrim | Stage5 시작 (현지화) | **Code** | **평문 잔존** |
| WF03 텍스트to쇼츠 | AI 영상 생성 | **Code** | **평문 잔존** |

Code 노드 3곳을 마저 없애려면 둘 중 하나다.
- Gemini 호출부만 `Code(프롬프트 조립) → HTTP(크리덴셜) → Code(파싱)` 로 분해. 활성 WF 라 회귀 위험 있음.
- n8n 호스트 관리자에게 노드 내 env 접근 허용을 요청 → 이후 `$env` 한 줄로 정리 가능.

## 크리덴셜 만드는 법 (Gemini 는 헤더 인증을 받는다)

Gemini 는 `?key=` 쿼리 대신 **`x-goog-api-key` 헤더**로도 인증된다. 그래서 범용 Header Auth 로 충분하다.

```bash
curl -X POST "$N8N_API_URL/api/v1/credentials" -H "X-N8N-API-KEY: $N8N_API_KEY" \
  -H 'Content-Type: application/json' -d '{
    "name": "Gemini API key (main)", "type": "httpHeaderAuth",
    "data": {"name": "x-goog-api-key", "value": "<KEY>",
             "allowedHttpRequestDomains": "domains",
             "allowedDomains": "generativelanguage.googleapis.com"}}'
```

`allowedDomains` 는 n8n 2.x 필수값이다(빠지면 스키마 오류). 도메인을 묶어두면 이 크리덴셜이
다른 호스트로 새어나가지 않는다.

노드 쪽은 URL 에서 `?key=...` 를 지우고 다음 3개를 세팅한다.

```json
"authentication": "predefinedCredentialType",
"nodeCredentialType": "httpHeaderAuth",
"credentials": {"httpHeaderAuth": {"id": "<credId>", "name": "Gemini API key (main)"}}
```

## 검증 레시피 (운영 WF 를 건드리지 않고 확인)

공개 API 에는 워크플로우 실행 엔드포인트가 없다. **임시 워크플로우 + 웹훅**으로 확인한다.

1. `POST /api/v1/workflows` 로 `Webhook(responseMode=lastNode) → 확인노드` 2노드짜리 임시 WF 생성
2. `POST /api/v1/workflows/{id}/activate`
3. `curl https://<n8n>/webhook/<path>` → 응답 본문이 그대로 결과
4. 실패 시 `GET /api/v1/executions?workflowId={id}&includeData=true` 로 노드별 에러 확인
5. `DELETE /api/v1/workflows/{id}`

## 주의

- 운영 WF 를 PUT 으로 고치기 전에 **원본을 파일로 백업**한다. PUT 은 전체 덮어쓰기다.
- `n8n/live-export/` 의 사본은 시점 스냅샷이라 **활성 여부·노드 상태가 라이브와 다를 수 있다**.
  판단은 항상 API 로 받은 라이브 정의 기준.
## 모델 일괄 교체 (2026-08-12)

라이브 104개를 훑어 Gemini 모델을 참조하는 **17개**를 찾아, `gemini-2.5-flash`·`gemini-2.0-flash`
→ **`gemini-3.5-flash`** 로 교체(16개 WF, 21개 노드). 앱의 `GEMINI_MODEL` 과 같은 모델이다.
(처음 3.1-flash-lite 로 넣었다가 flash 등급으로 상향. **`gemini-3.1-flash` 라는 id 는 없다** —
3.1 계열은 lite/image/tts/pro 뿐이라, 3.1 급 flash 를 원하면 정식 flash 는 3.5 가 최저선이다.)

- `gemini-2.0-flash` 는 **이미 API 목록에서 사라진 상태**였다(WF01 경쟁사모니터링, WF02 뉴스브리핑,
  WF03 텍스트to쇼츠 — 셋 다 비활성이라 장애로 드러나지 않았을 뿐, 돌렸으면 실패).
- 활성 3개 포함: WF-AUTO-SCRIPT, WF-LF-QUIZ, WF201 정치쇼츠.
- **AF01-쇼핑펌프-쇼츠(비활성)만 `gemini-2.5-pro` 로 남겨뒀다.** pro 계열은 정식 후속이 없고
  (`gemini-3.1-pro-preview` = 프리뷰, `gemini-pro-latest` = 자동이동 별칭) 선택이 필요하다.
- 검증: 크리덴셜 + 신규 모델 조합을 임시 WF 로 실호출 → 정상 응답 확인. 앱은 평문·구조화 출력 양쪽 실호출 확인.
- 비용은 2.5-flash 대비 오른다($0.30/$2.50 → $1.50/$9.00). 비용이 문제되면 가벼운 노드부터
  `gemini-3.5-flash-lite`·`gemini-3.1-flash-lite` 로 내리면 된다.
