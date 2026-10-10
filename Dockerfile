FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# TLS 루트 인증서(외부 API HTTPS 호출용)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY main.py ./main.py
COPY models.py ./models.py
COPY static ./static
COPY app ./app
COPY scripts ./scripts

# 로컬(docker compose)은 8028, Cloud Run 은 런타임이 $PORT(기본 8080)를 주입한다.
# exec 형식은 변수 치환이 안 되므로 sh -c 로 감싼다.
ENV PORT=8028
EXPOSE 8028

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT}"]