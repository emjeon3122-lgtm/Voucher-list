# 상품권 수불 관리 — Python 공식 이미지 하나로 실행 (DB 서버 불필요)
FROM python:3.12-slim

# TZ: 서명·대장 시각과 자동 백업 시각을 판단하는 시간대
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Seoul \
    DATA_DIR=/data \
    HOST=127.0.0.1 \
    PORT=7030

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY wsgi.py gunicorn.conf.py VERSION ./

# 기본 실행 계정(일반 사용자). docker-compose.yml 의 user(APP_UID:APP_GID)로 NAS 계정에 맞춘다.
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin app && mkdir -p /data && chown app /data
USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"7030\")}/healthz', timeout=4)" || exit 1

CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
