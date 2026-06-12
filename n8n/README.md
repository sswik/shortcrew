# n8n 워크플로우 템플릿

이 폴더에는 교육에서 사용하는 n8n 워크플로우 JSON 파일이 포함되어 있습니다.

## 사용 방법

1. n8n Cloud (https://n8n.io) 에 로그인합니다
2. Workflows > Import from File 을 선택합니다
3. 이 폴더의 JSON 파일을 업로드합니다
4. Credentials (인증 정보)를 본인 것으로 설정합니다:
   - GitHub: Personal Access Token
   - Slack: Webhook URL 또는 Bot Token
5. JSON 내 `{owner}/{repo}` 플레이스홀더를 본인 저장소로 교체합니다

## 워크플로우 목록

| # | 파일 | 워크플로우명 | 트리거 | 동작 | 주차 |
|---|------|-------------|--------|------|------|
| 01 | 01-github-issue-slack.json | GitHub Issue -> Slack 알림 | GitHub Issue 생성/수정 | Slack 채널에 이슈 정보 전송 | W2 |
| 02 | 02-weekly-summary-slack.json | 주간 요약 -> Slack 전송 | 매주 금요일 (Cron) | GitHub Issues 요약 -> Slack 전송 | W2 |
| 03 | 03-deploy-notification.json | 배포 완료 -> Slack 알림 | Webhook (GitHub Actions 호출) | 배포 상태 Slack 전송 | W5 |
| 04 | 04-slack-ai-github-agent.json | PM 어시스턴트 (Chat UI) | n8n Chat UI | AI Agent로 프로젝트 현황 질의 | W5 |
| 05 | 05-slack-pm-agent.json | Slack PM 어시스턴트 | Slack 슬래시 명령 | Slack에서 AI Agent로 GitHub 질의 | W5 |

## 사전 설정 필요 항목

| 서비스 | 필요한 인증 | 설정 위치 | 대상 워크플로우 |
|--------|-----------|-----------|----------------|
| GitHub | Personal Access Token (repo, issues 권한) | n8n > Credentials > GitHub API | 01, 02 |
| GitHub | PAT (Header Auth 형식) | n8n > Credentials > HTTP Header Auth | 04, 05 |
| Slack | Incoming Webhook URL | 워크플로우 내 HTTP Request 노드에 직접 입력 | 01, 02, 03 |
| Google Gemini | API Key | n8n > Credentials > Google Gemini API | 04, 05 |

> Slack Incoming Webhook URL은 n8n Credential이 아닙니다. 워크플로우 내 HTTP Request 노드에 직접 입력합니다.

## WF 04-05 아키텍처 (AI Agent)

**WF 04 - Chat UI Agent**: n8n 내장 Chat UI에서 자연어로 프로젝트 현황을 질의합니다.
- 트리거: Chat Trigger (n8n 내부 URL)
- LLM: Google Gemini 2.0 Flash
- 도구: Issues (필터링 가능), Milestones, Repo Info
- 메모리: Buffer Window (최근 10턴)

**WF 05 - Slack PM Agent**: Slack 슬래시 명령(`/깃 [질문]`)으로 프로젝트 현황을 질의합니다.
- 아키텍처: `Slack /깃 [질문] -> n8n Webhook -> AI Agent (Gemini) -> GitHub API Tools -> Slack`
- 3초 타임아웃 방지: `responseNode` + 즉시 응답 패턴
- 도구: Open Issues, Closed Issues, Milestones (각각 별도 도구)
- `maxLength` 조정 필요: GitHub API 응답이 큰 경우 12000까지 확장

## GitHub Actions에서 n8n Webhook 호출 설정

`.github/workflows/ci.yml`에서 n8n Webhook을 호출하는 방법:

```yaml
# ci.yml의 배포 완료 후 단계에 추가
- name: Notify n8n
  if: success()
  run: |
    curl -X POST "${{ secrets.N8N_WEBHOOK_URL }}" \
      -H "Content-Type: application/json" \
      -d '{"repo":"${{ github.repository }}","status":"success","ref":"${{ github.ref }}"}'
```

GitHub 저장소의 Settings > Secrets에 `N8N_WEBHOOK_URL`을 등록해야 합니다.
