#!/bin/ash
# Open-FDD MQTT entrypoint: volume kits often land as root:0600; mosquitto runs as 1883.
# Private keys must NOT be world-readable (Nessus / CIS finding). Certs/ACL need group read.
# Permission repair failures fail closed when the key is world-readable or group-writable
# for others; read-only mounts are accepted only when mode is already 600/640.
set -e

PUID="${PUID:-1883}"
PGID="${PGID:-1883}"

key_mode_ok() {
  # BusyBox/ash: octal mode from stat -c %a (e.g. 640).
  mode="$(stat -c '%a' "$1" 2>/dev/null || echo '')"
  case "$mode" in
    600|640) return 0 ;;
    *) return 1 ;;
  esac
}

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
    key=/mosquitto/certs/server.key.pem
    if chown "${PUID}:${PGID}" "$key" 2>/dev/null; then
      # Writable mount: require successful restrictive mode.
      chmod 640 "$key" || {
        echo "openfdd-mqtt: FATAL cannot chmod 640 $key" >&2
        exit 1
      }
    fi
    if ! key_mode_ok "$key"; then
      echo "openfdd-mqtt: FATAL $key must be mode 600 or 640 (got $(stat -c '%a' "$key" 2>/dev/null || echo unknown))" >&2
      exit 1
    fi
    # Refuse world-readable even if repair was skipped (read-only volume).
    others="$(stat -c '%a' "$key" | awk '{print substr($0,length,1)}')"
    if [ "$others" != "0" ]; then
      echo "openfdd-mqtt: FATAL $key is world-accessible" >&2
      exit 1
    fi
  fi
fi

exec /docker-entrypoint.sh "$@"
