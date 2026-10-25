#!/bin/sh
# Runs as root only to fix the owner of /config, then starts Rotatarr as PUID:PGID.
set -e
PUID="${PUID:-99}"
PGID="${PGID:-100}"

if [ "$(id -u)" = "0" ]; then
  mkdir -p "$ROTATARR_CONFIG_DIR"
  chown -R "$PUID:$PGID" "$ROTATARR_CONFIG_DIR"
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups python -m rotatarr
fi
exec python -m rotatarr
