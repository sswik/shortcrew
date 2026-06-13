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

EXPOSE 8028

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8028"]