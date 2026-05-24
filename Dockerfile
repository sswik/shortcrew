FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# supercronic: shorts-review-cron 서비스에서 동일 이미지로 일일 스케줄 실행
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && ARCH="$(dpkg --print-architecture)" \
    && case "$ARCH" in amd64) SC=amd64 ;; arm64) SC=arm64 ;; *) echo "unsupported arch: $ARCH" >&2; exit 1 ;; esac \
    && curl -fsSL "https://github.com/aptible/supercronic/releases/download/v0.2.33/supercronic-linux-${SC}" -o /usr/local/bin/supercronic \
    && chmod +x /usr/local/bin/supercronic \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY main.py ./main.py
COPY models.py ./models.py
COPY static ./static
COPY app ./app
COPY scripts ./scripts
COPY deploy/shorts-review-cron.crontab ./deploy/shorts-review-cron.crontab

EXPOSE 8028

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8028"]