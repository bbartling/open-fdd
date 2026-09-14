#!/bin/ash
# Open-FDD wrapper: volume kit uploads often land as root:0600; mosquitto drops to uid 1883.
# Without world/group read, broker exits: "Unable to load server key file … Permission denied".
set -e

PUID="${PUID:-1883}"
PGID="${PGID:-1883}"

if [ "$(id -u)" = "0" ] && [ -d /mosquitto/certs ]; then
  for f in /mosquitto/certs/ca.pem \
    /mosquitto/certs/server.cert.pem \
    /mosquitto/certs/server.key.pem \
    /mosquitto/certs/acl; do
    if [ -e "$f" ]; then
      chmod a+r "$f" 2>/dev/null || true
      chown "${PUID}:${PGID}" "$f" 2>/dev/null || true
    fi
  done
fi

exec /docker-entrypoint.sh "$@"
