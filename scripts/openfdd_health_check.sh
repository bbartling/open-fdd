#!/usr/bin/env bash
# Quick health check — local bridge, optional LAN/Caddy, optional auth login.
#
#   ./scripts/openfdd_health_check.sh
#   ./scripts/openfdd_health_check.sh --remote
#   OPENFDD_BRIDGE_BASE=https://192.168.204.55 ./scripts/openfdd_health_check.sh --remote --auth
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

BASE="${OPENFDD_BRIDGE_BASE:-http://127.0.0.1:8080}"
REMOTE=0
AUTH=0
CURL_TLS=()
if [[ "$BASE" == https://* ]]; then CURL_TLS=(-k); fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote) REMOTE=1 ;;
    --auth) AUTH=1 ;;
    --base) BASE="$2"; shift 2 ;;
    -h|--help)
      cat <<'EOF'
Usage: scripts/openfdd_health_check.sh [--remote] [--auth] [--base URL]

Checks /health, /api/health, optional /api/health/stack, and SPA root.
With --remote, also probes https://<LAN-IP>/health via Caddy.
With --auth, verifies integrator login + /api/auth/me.
EOF
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

fail=0
LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

check() {
  local name="$1"
  local url="$2"
  local bearer="${3:-}"
  local code body
  local curl_args=("${CURL_TLS[@]}" -sS -o /tmp/openfdd_health_body.json -w '%{http_code}' --max-time 8)
  if [[ -n "$bearer" ]]; then
    curl_args+=(-H "Authorization: Bearer $bearer")
  fi
  code="$(curl "${curl_args[@]}" "$url" 2>/dev/null || echo 000)"
  if [[ "$code" != "200" ]]; then
    echo "FAIL: $name HTTP $code ($url)" >&2
    fail=1
    return
  fi
  body="$(cat /tmp/openfdd_health_body.json 2>/dev/null || true)"
  if [[ "$body" == *'"ok":true'* || "$body" == *'"ok": true'* || "$url" == *"/health"* ]]; then
    echo "OK: $name ($code)"
  else
    echo "WARN: $name HTTP $code but body may not be ok"
  fi
}

df_line="$(df -h / | tail -1)"
avail_gb="$(df --output=avail / | tail -1 | tr -d ' ')"
avail_gb=$((avail_gb / 1024 / 1024))
mem_mb="$(awk '/MemAvailable:/ {print int($2/1024)}' /proc/meminfo)"
echo "Host: $df_line | MemAvailable: ${mem_mb}MB"
if [[ "$avail_gb" -lt 5 ]]; then
  echo "WARN: low disk (${avail_gb}GB free) — run ./scripts/openfdd_docker_maintenance.sh" >&2
fi

echo "Bridge base: $BASE"
check public-health "$BASE/health"
check api-health "$BASE/api/health"

token=""
if [[ "$AUTH" == "1" ]]; then
  token="$(openfdd_auth_login_token "$BASE" "$ROOT/workspace/auth.env.local" integrator 2>/dev/null || true)"
  if [[ -z "$token" ]]; then
    echo "FAIL: integrator login" >&2
    fail=1
  else
    me="$(curl "${CURL_TLS[@]}" -fsS "$BASE/api/auth/me" -H "Authorization: Bearer $token" | jq -r '.role // empty')"
    echo "OK: integrator login (role=${me:-integrator})"
    check stack-health "$BASE/api/health/stack" "$token"
  fi
else
  stack_code="$(curl "${CURL_TLS[@]}" -sS -o /dev/null -w '%{http_code}' --max-time 8 "$BASE/api/health/stack" 2>/dev/null || echo 000)"
  if [[ "$stack_code" == "401" ]]; then
    echo "OK: stack-health (401 without auth — expected)"
  elif [[ "$stack_code" == "200" ]]; then
    echo "OK: stack-health (200)"
  else
    echo "FAIL: stack-health HTTP $stack_code" >&2
    fail=1
  fi
fi

spa_code="$(curl "${CURL_TLS[@]}" -sS -o /dev/null -w '%{http_code}' --max-time 8 "$BASE/" 2>/dev/null || echo 000)"
if [[ "$spa_code" == "200" ]]; then
  echo "OK: SPA root ($spa_code)"
else
  echo "FAIL: SPA root HTTP $spa_code" >&2
  fail=1
fi

if [[ "$REMOTE" == "1" && -n "$LAN_IP" ]]; then
  if curl -kfsS --max-time 8 "https://${LAN_IP}/health" >/dev/null 2>&1; then
    echo "OK: Caddy HTTPS https://${LAN_IP}/health"
  else
    echo "FAIL: Caddy HTTPS https://${LAN_IP}/health" >&2
    fail=1
  fi
fi

rm -f /tmp/openfdd_health_body.json

if [[ "$fail" -ne 0 ]]; then
  echo "Health check FAILED" >&2
  exit 1
fi
echo "Health check PASS"
