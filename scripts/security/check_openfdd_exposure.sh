#!/usr/bin/env bash
# Open-FDD-specific exposure checks: Docker, Caddy/TLS, Ollama, bridge ports.
# Read-only — run on edge host. Pair with check_host_security.sh and LAN ZAP/Nmap scans.
#
#   ./scripts/security/check_openfdd_exposure.sh
#   ./scripts/security/check_openfdd_exposure.sh --edge-ip 100.122.106.124
set -euo pipefail

EDGE_IP="${EDGE_IP:-}"
REPORT_DIR="${REPORT_DIR:-openfdd-security-report}"
COMPOSE_DIR="${COMPOSE_DIR:-}"
FAILURES=0

usage() {
  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

log_ok() { echo "OK: $*"; }
log_warn() { echo "WARN: $*"; }
log_fail() { echo "FAIL: $*"; FAILURES=$((FAILURES + 1)); }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --edge-ip) EDGE_IP="$2"; shift 2 ;;
    --report-dir) REPORT_DIR="$2"; shift 2 ;;
    --compose-dir) COMPOSE_DIR="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown: $1" >&2; usage 1 ;;
  esac
done

section() {
  echo ""
  echo "============================================================"
  echo "$1"
  echo "============================================================"
}

if [[ "$REPORT_DIR" != /* ]]; then
  BASE_DIR="$(pwd)/${REPORT_DIR}"
else
  BASE_DIR="$REPORT_DIR"
fi
mkdir -p "$BASE_DIR"
EXPO_REPORT="${BASE_DIR}/06-openfdd-exposure-check.txt"
exec > >(tee -a "$EXPO_REPORT") 2>&1

section "Open-FDD exposure check — $(date '+%Y-%m-%d %H:%M:%S')"

if [[ -z "$EDGE_IP" ]]; then
  EDGE_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [[ -n "$EDGE_IP" ]] && log_ok "EDGE_IP auto-detected: ${EDGE_IP}"
fi

section "Docker Compose services"
if [[ -z "$COMPOSE_DIR" ]]; then
  for d in "$HOME/open-fdd" /var/openfdd "$PWD"; do
    if [[ -f "${d}/docker-compose.yml" ]]; then
      COMPOSE_DIR="$d"
      break
    fi
  done
fi
if [[ -n "$COMPOSE_DIR" && -f "${COMPOSE_DIR}/docker-compose.yml" ]]; then
  log_ok "Compose dir: ${COMPOSE_DIR}"
  (cd "$COMPOSE_DIR" && docker compose ps 2>/dev/null) || docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null | head -20
else
  log_warn "docker-compose.yml not found — set --compose-dir"
  docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null | head -20 || true
fi

section "Expected port posture (OT LAN)"
echo "From LAN, expect: :80 or :443 (Caddy) open; :8765 closed; :8090 closed; :11434 closed"
if command -v ss >/dev/null 2>&1; then
  for port in 80 443 8765 8090 11434; do
    line="$(ss -tulpn 2>/dev/null | grep -E ":${port} " || true)"
    if [[ -n "$line" ]]; then
      echo "  :${port} ${line}"
      case "$port" in
        8765|8090)
          if echo "$line" | grep -qE '0\.0\.0\.0|\[::\]'; then
            log_fail "Port ${port} listening on all interfaces — should be loopback or internal only"
          else
            log_ok "Port ${port} not on 0.0.0.0"
          fi
          ;;
        11434)
          if echo "$line" | grep -qE '0\.0\.0\.0:11434|\[::\]:11434'; then
            log_fail "Ollama on 0.0.0.0:11434 — CRITICAL: no auth; set OLLAMA_HOST=127.0.0.1:11434"
          elif echo "$line" | grep -q '127.0.0.1:11434'; then
            log_ok "Ollama loopback only (127.0.0.1:11434)"
          else
            log_warn "Ollama bind: ${line}"
          fi
          ;;
      esac
    else
      echo "  :${port} not listening"
    fi
  done
fi

section "Ollama reachability (authless API)"
if curl -sf --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  log_ok "Ollama responds on loopback (expected for agent chat)"
else
  log_ok "Ollama not on loopback (optional service)"
fi
if [[ -n "$EDGE_IP" ]]; then
  if curl -sf --max-time 3 "http://${EDGE_IP}:11434/api/tags" >/dev/null 2>&1; then
    log_fail "Ollama reachable from host LAN IP ${EDGE_IP}:11434 — must not be exposed"
  else
    log_ok "Ollama not reachable via ${EDGE_IP}:11434 (good)"
  fi
  echo "From another LAN machine, verify: curl -sf --max-time 3 http://${EDGE_IP}:11434/api/tags (should fail)"
fi

section "Caddy / TLS"
for cert in /etc/openfdd/caddy/cert.pem workspace/deploy/caddy/certs/cert.pem; do
  if [[ -f "$cert" ]]; then
    log_ok "Cert found: ${cert}"
    if command -v openssl >/dev/null 2>&1; then
      openssl x509 -in "$cert" -noout -subject -dates 2>/dev/null || true
    fi
  fi
done
if command -v systemctl >/dev/null 2>&1 && systemctl is-active caddy >/dev/null 2>&1; then
  log_ok "Caddy systemd active"
elif ss -tulpn 2>/dev/null | grep -q ':80 '; then
  log_ok "Something listening on :80"
else
  log_warn "Caddy/:80 not detected"
fi
echo "Self-signed TLS produces Nessus Medium findings — expected for lab; use enterprise CA for clean scans"

section "Docker image tags (if compose dir set)"
if [[ -n "$COMPOSE_DIR" && -f "${COMPOSE_DIR}/docker-compose.yml" ]]; then
  (cd "$COMPOSE_DIR" && docker compose images 2>/dev/null) || true
fi

section "Done"
echo "Report: ${EXPO_REPORT}"
if [[ "$FAILURES" -gt 0 ]]; then
  echo "Exposure check FAILED (${FAILURES} issue(s)) — see docs/security/tenable-remediation.md" >&2
  exit 1
fi
echo "Exposure check PASSED"
