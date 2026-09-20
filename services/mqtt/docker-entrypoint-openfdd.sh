#!/bin/ash
# Open-FDD MQTT entrypoint: volume kits often land as root:0600; mosquitto runs as 1883.
# Private keys must NOT be world-readable (Nessus / CIS finding). Certs/ACL need group read.
set -e

PUID="${PUID:-1883}"
PGID="${PGID:-1883}"

if [ "$(id -u)" = "0" ] && [ -d /mosquitto/certs ]; then
  for f in /mosquitto/certs/ca.pem \
    /mosquitto/certs/server.cert.pem \
    /mosquitto/certs/acl; do
    if [ -e "$f" ]; then
      chown "${PUID}:${PGID}" "$f" 2>/dev/null || true
      chmod 644 "$f" 2>/dev/null || true
    fi
  done
  if [ -e /mosquitto/certs/server.key.pem ]; then
    chown "${PUID}:${PGID}" /mosquitto/certs/server.key.pem 2>/dev/null || true
    # owner read + group read for mosquitto uid; never world-readable
    chmod 640 /mosquitto/certs/server.key.pem 2>/dev/null || true
  fi
fi

exec /docker-entrypoint.sh "$@"
