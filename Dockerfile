FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ROTATARR_CONFIG_DIR=/config \
    PORT=7373 \
    TZ=Etc/UTC \
    PUID=99 \
    PGID=100

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY rotatarr ./rotatarr
COPY entrypoint.sh /entrypoint.sh

VOLUME /config
EXPOSE 7373

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -m rotatarr.healthcheck

ENTRYPOINT ["/entrypoint.sh"]
