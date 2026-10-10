#!/usr/bin/env bash
# `.env` / `google-key.json` 을 Secret Manager 에 올리고 Cloud Run 이 새 버전을 집게 한다.
#
# 왜 필요한가
#   GitHub Actions 자동배포는 `gcloud run deploy --image` 만 호출한다(워크플로에 시크릿을
#   중복 기재하지 않으려는 의도). 서비스의 env·시크릿 설정은 기존 리비전에서 승계되므로
#   **코드 변경은 푸시로 반영되지만 `.env` 변경은 반영되지 않는다.**
#   `.env` 를 고쳤으면 이 스크립트를 한 번 돌린다.
#
#   `--set-secrets` 는 `:latest` 로 걸려 있지만, Cloud Run 은 실행 중 리비전의 마운트를
#   다시 읽지 않는다. 새 리비전이 떠야 새 시크릿 버전이 적용된다 → 마지막에 강제 갱신.
#
# 사용법
#   scripts/sync-env.sh            # .env 만
#   scripts/sync-env.sh --with-key # google-key.json 도 함께
set -euo pipefail

PROJECT=sswik-2026
REGION=asia-northeast1
SERVICE=shortcrew
ENV_SECRET=shortcrew-env
KEY_SECRET=shortcrew-google-key

cd "$(dirname "$0")/.."

[ -f .env ] || { echo "ERROR: .env 가 없다 ($(pwd))" >&2; exit 1; }

echo "[1/3] $ENV_SECRET 새 버전 업로드"
gcloud secrets versions add "$ENV_SECRET" --data-file=.env --project "$PROJECT" >/dev/null
echo "      완료: $(gcloud secrets versions list "$ENV_SECRET" --project "$PROJECT" \
        --limit=1 --format='value(name)')"

if [ "${1:-}" = "--with-key" ]; then
  [ -f google-key.json ] || { echo "ERROR: google-key.json 이 없다" >&2; exit 1; }
  echo "[2/3] $KEY_SECRET 새 버전 업로드"
  gcloud secrets versions add "$KEY_SECRET" --data-file=google-key.json --project "$PROJECT" >/dev/null
else
  echo "[2/3] google-key.json 건너뜀 (--with-key 로 포함)"
fi

echo "[3/3] Cloud Run 새 리비전 배포(시크릿 재마운트)"
# 이미지·설정은 그대로 두고 리비전만 새로 띄운다.
gcloud run services update "$SERVICE" --region "$REGION" --project "$PROJECT" \
  --update-labels "envsync=$(date +%Y%m%d-%H%M%S)" --quiet >/dev/null

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" \
      --format='value(status.url)')
REV=$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" \
      --format='value(status.latestReadyRevisionName)')

for i in $(seq 1 10); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$URL/health" || echo 000)
  if [ "$CODE" = "200" ]; then
    echo "완료: $REV 가 트래픽을 받는 중 ($URL)"
    exit 0
  fi
  echo "      헬스 재시도 $i: HTTP $CODE"
  sleep 10
done

echo "ERROR: 헬스 체크 실패 — 콘솔에서 리비전 로그를 확인하라" >&2
exit 1
