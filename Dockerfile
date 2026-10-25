FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ROTATARR_CONFIG_DIR=/config \
    PORT=7373 \
    TZ=Etc/UTC

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY rotatarr ./rotatarr

VOLUME /config
EXPOSE 7373

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/state', timeout=4)" || exit 1

CMD ["python", "-m", "rotatarr"]
