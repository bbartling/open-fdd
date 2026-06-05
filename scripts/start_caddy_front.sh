#!/usr/bin/env bash
# Start host Caddy (:80 → bridge :8765) for production-like LAN access / OWASP ZAP scans.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="${ROOT}/workspace/.local-run"
CADDY_PID="${PID_DIR}/caddy.pid"
CADDY_LOG="${PID_DIR}/caddy.log"
mkdir -p "$PID_DIR"

if [[ -f "${ROOT}/workspace/caddy.env.local" ]]; then
  # shellcheck disable=SC1091
  set -a && source "${ROOT}/workspace/caddy.env.local" && set +a
fi

OFDD_CADDY_ENABLED="${OFDD_CADDY_ENABLED:-1}"
OFDD_CADDY_MODE="${OFDD_CADDY_MODE:-http}"
OFDD_BRIDGE_PORT="${OFDD_BRIDGE_PORT:-8765}"
OFDD_CADDY_HTTP_PORT="${OFDD_CADDY_HTTP_PORT:-80}"

if [[ "$OFDD_CADDY_ENABLED" != "1" || "$OFDD_CADDY_MODE" == "off" ]]; then
  echo "Caddy disabled (OFDD_CADDY_ENABLED / OFDD_CADDY_MODE) — bridge is direct on :${OFDD_BRIDGE_PORT}" >&2
  exit 0
fi

command -v caddy >/dev/null 2>&1 || { echo "Install caddy: sudo apt install caddy" >&2; exit 1; }

if [[ -f "$CADDY_PID" ]] && kill -0 "$(cat "$CADDY_PID")" 2>/dev/null; then
  kill "$(cat "$CADDY_PID")" 2>/dev/null || true
  sleep 1
  rm -f "$CADDY_PID"
fi

CFG="${PID_DIR}/Caddyfile"
if [[ "$OFDD_CADDY_MODE" == "tls" ]]; then
  cert_dir="${ROOT}/workspace/deploy/caddy/certs"
  if [[ ! -f "${cert_dir}/cert.pem" ]]; then
    OFDD_CADDY_TLS_CN="${OFDD_CADDY_TLS_CN:-openfdd.local}" "${ROOT}/scripts/setup_caddy_certs.sh"
  fi
  cat >"$CFG" <<EOF
:80 {
	redir https://{host}{uri} permanent
}
:443 {
	tls ${cert_dir}/cert.pem ${cert_dir}/key.pem
	header {
		Strict-Transport-Security "max-age=31536000; includeSubDomains"
		X-Content-Type-Options nosniff
		X-Frame-Options SAMEORIGIN
		Referrer-Policy strict-origin-when-cross-origin
	}
	reverse_proxy 127.0.0.1:${OFDD_BRIDGE_PORT}
}
EOF
else
  cat >"$CFG" <<EOF
:${OFDD_CADDY_HTTP_PORT} {
	header {
		X-Content-Type-Options nosniff
		X-Frame-Options SAMEORIGIN
		Referrer-Policy strict-origin-when-cross-origin
	}
	reverse_proxy 127.0.0.1:${OFDD_BRIDGE_PORT}
}
EOF
fi

bin="$(command -v caddy)"
if ! getcap "$bin" 2>/dev/null | grep -q cap_net_bind_service; then
  sudo -n setcap 'cap_net_bind_service=+ep' "$bin" 2>/dev/null || true
fi

: >"$CADDY_LOG"
nohup caddy run --config "$CFG" --adapter caddyfile >>"$CADDY_LOG" 2>&1 &
echo $! >"$CADDY_PID"

entry="http://127.0.0.1:${OFDD_CADDY_HTTP_PORT}/"
[[ "$OFDD_CADDY_MODE" == "tls" ]] && entry="https://127.0.0.1/"
for _ in $(seq 1 30); do
  if curl -sfk "${entry%/}/health" >/dev/null 2>&1; then
    LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    echo "Caddy pid=$(cat "$CADDY_PID") → ${entry}"
    echo "LAN entry: http://${LAN_IP}:${OFDD_CADDY_HTTP_PORT}/"
    exit 0
  fi
  sleep 0.5
done
echo "Caddy started but /health not ready — see ${CADDY_LOG}" >&2
exit 1
