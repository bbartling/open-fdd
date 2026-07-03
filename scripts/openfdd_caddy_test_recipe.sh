#!/usr/bin/env bash
# Caddy ingress test recipes — bootstrap direct, caddy-http, or caddy-tls (no git clone).
#
#   ./scripts/openfdd_caddy_test_recipe.sh direct      # stop Caddy; bench uses :8080 only
#   ./scripts/openfdd_caddy_test_recipe.sh caddy-http  # Caddy :80 → bridge
#   ./scripts/openfdd_caddy_test_recipe.sh caddy-tls   # Caddy :443 TLS + :80 redirect
#   ./scripts/openfdd_caddy_test_recipe.sh stop
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"

export OPENFDD_COMPOSE_ROOT="${OPENFDD_COMPOSE_ROOT:-$ROOT}"
RECIPE="${1:-status}"
CERT_DIR="${OPENFDD_CADDY_CERT_DIR:-$ROOT/workspace/deploy/caddy/certs}"
COMPOSE="$(openfdd_rust_resolve_compose_file "$ROOT")"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

openfdd_caddy_restore_bridge() {
  openfdd_rust_ensure_bridge_host_network "$ROOT" "http://127.0.0.1:8080/api/health" \
    || echo "WARN: bridge host-network restore failed — see docker-compose.override.yml" >&2
}

openfdd_caddy_stop() {
  docker rm -f openfdd-caddy >/dev/null 2>&1 || true
  openfdd_caddy_restore_bridge
  log "Caddy stopped (direct / bridge :8080 only)"
}

openfdd_caddy_ensure_certs() {
  mkdir -p "$CERT_DIR"
  if [[ -f "$CERT_DIR/cert.pem" && -f "$CERT_DIR/key.pem" ]]; then
    log "TLS certs present in $CERT_DIR"
    return 0
  fi
  log "Generating self-signed TLS certs (openfdd-edge tls generate equivalent)"
  # Try edge binary in running bridge container first
  local cid
  cid="$(docker ps -qf 'name=openfdd-bridge' 2>/dev/null | head -1 || true)"
  if [[ -n "$cid" ]] && docker exec "$cid" sh -c 'command -v openfdd-edge || command -v open_fdd_edge_prototype' >/dev/null 2>&1; then
    local bin
    bin="$(docker exec "$cid" sh -c 'command -v openfdd-edge || command -v open_fdd_edge_prototype')"
    if docker exec "$cid" "$bin" tls generate --help >/dev/null 2>&1; then
      docker exec "$cid" "$bin" tls generate 2>/dev/null || true
    fi
  fi
  if [[ ! -f "$CERT_DIR/cert.pem" ]]; then
    openssl req -x509 -newkey rsa:2048 -nodes \
      -keyout "$CERT_DIR/key.pem" -out "$CERT_DIR/cert.pem" -days 365 \
      -subj "/CN=${OPENFDD_CADDY_TLS_CN:-openfdd.local}" \
      -addext "subjectAltName=DNS:${OPENFDD_CADDY_HOSTNAME:-openfdd.local},DNS:localhost,IP:127.0.0.1" \
      2>/dev/null || {
        openssl req -x509 -newkey rsa:2048 -nodes \
          -keyout "$CERT_DIR/key.pem" -out "$CERT_DIR/cert.pem" -days 365 \
          -subj "/CN=openfdd.local"
      }
  fi
  [[ -f "$CERT_DIR/cert.pem" && -f "$CERT_DIR/key.pem" ]] || {
    echo "ERROR: failed to create TLS certs in $CERT_DIR" >&2
    return 1
  }
}

openfdd_caddy_wait_healthy() {
  local i
  for i in $(seq 1 30); do
    if docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null | grep -q '^openfdd-caddy .*Up'; then
      sleep 2
      return 0
    fi
    sleep 1
  done
  echo "ERROR: openfdd-caddy did not start" >&2
  docker logs openfdd-caddy 2>&1 | tail -20 || true
  return 1
}

openfdd_caddy_up_http() {
  openfdd_caddy_stop
  openfdd_caddy_restore_bridge
  log "Starting caddy-http profile (:80 → 127.0.0.1:8080, host network)"
  openfdd_rust_dcompose "$ROOT" --profile full-edge --profile caddy-http \
    up -d --force-recreate --no-deps openfdd-caddy-http 2>&1
  openfdd_caddy_wait_healthy
  curl -fsS -m 10 "http://127.0.0.1:${OPENFDD_CADDY_HTTP_PORT:-80}/api/health" | jq -e '.ok == true' >/dev/null \
    || { echo "ERROR: Caddy HTTP health failed" >&2; return 1; }
  log "caddy-http ready http://127.0.0.1:${OPENFDD_CADDY_HTTP_PORT:-80}"
}

openfdd_caddy_up_tls() {
  openfdd_caddy_stop
  openfdd_caddy_ensure_certs
  openfdd_caddy_restore_bridge
  log "Starting caddy-tls profile (:443 TLS, :80 redirect; host network → 127.0.0.1:8080)"
  openfdd_rust_dcompose "$ROOT" --profile full-edge --profile caddy-tls \
    up -d --force-recreate --no-deps openfdd-caddy-tls 2>&1
  openfdd_caddy_wait_healthy
  curl -kfsS -m 10 "https://127.0.0.1:${OPENFDD_CADDY_HTTPS_PORT:-443}/api/health" | jq -e '.ok == true' >/dev/null \
    || { echo "ERROR: Caddy TLS health failed" >&2; return 1; }
  log "caddy-tls ready https://127.0.0.1:${OPENFDD_CADDY_HTTPS_PORT:-443}"
}

openfdd_caddy_status() {
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx openfdd-caddy; then
    docker inspect openfdd-caddy --format 'mode={{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
      | grep OPENFDD_CADDY_MODE || true
    docker ps --filter name=openfdd-caddy --format '{{.Names}} {{.Status}} {{.Ports}}'
  else
    echo "direct (no Caddy — use http://127.0.0.1:8080)"
  fi
}

case "$RECIPE" in
  direct|stop)
    openfdd_caddy_stop
    ;;
  caddy-http|http)
    openfdd_caddy_up_http
    ;;
  caddy-tls|tls)
    openfdd_caddy_up_tls
    ;;
  status)
    openfdd_caddy_status
    ;;
  *)
    echo "Usage: $0 {direct|stop|caddy-http|caddy-tls|status}" >&2
    exit 1
    ;;
esac
