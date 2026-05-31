#!/usr/bin/env bash
# Insurance checks after Open-FDD ansible deploy — run from bensserver (control machine).
#
# Examples:
#   ./scripts/post_deploy_check.sh --host 192.168.204.12
#   ./scripts/post_deploy_check.sh --inventory inventory.yml --limit bacnet_pi
#   OFDD_OPERATOR_USER=operator OFDD_OPERATOR_PASSWORD=secret ./scripts/post_deploy_check.sh --host 192.168.204.12
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ANSIBLE_DIR="$(cd "$DIR/.." && pwd)"
ROOT="$(cd "$ANSIBLE_DIR/../.." && pwd)"

HOST=""
INV="${ANSIBLE_INVENTORY:-${ANSIBLE_DIR}/inventory.yml}"
LIMIT=""
SSH_USER="${ANSIBLE_REMOTE_USER:-ben}"
CADDY_TLS=0
AUTH_ENV="${ROOT}/workspace/auth.env.local"
RETRIES=12
DELAY=5
FAILURES=0

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

log_ok() { printf '  OK   %s\n' "$*"; }
log_fail() { printf '  FAIL %s\n' "$*" >&2; FAILURES=$((FAILURES + 1)); }

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage 0 ;;
    --host) HOST="$2"; shift 2 ;;
    --inventory) INV="$2"; shift 2 ;;
    --limit) LIMIT="$2"; shift 2 ;;
    --ssh-user) SSH_USER="$2"; shift 2 ;;
    --auth-env) AUTH_ENV="$2"; shift 2 ;;
    --tls) CADDY_TLS=1; shift ;;
    --retries) RETRIES="$2"; shift 2 ;;
    --delay) DELAY="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; usage 1 ;;
  esac
done

if [[ -z "$HOST" && -n "$LIMIT" && -f "$INV" ]]; then
  if command -v ansible-inventory >/dev/null 2>&1; then
    HOST="$(ansible-inventory -i "$INV" --host "$LIMIT" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("ansible_host",""))' || true)"
  fi
fi

if [[ -z "$HOST" ]]; then
  echo "Need --host IP or --limit NAME with a valid inventory." >&2
  usage 1
fi

scheme=http
[[ "$CADDY_TLS" == 1 ]] && scheme=https
BASE="${scheme}://${HOST}"
CURL=(curl -fsS --connect-timeout 5 --max-time 20)
[[ "$CADDY_TLS" == 1 ]] && CURL+=(-k)

echo "Open-FDD post-deploy check → ${HOST}"

wait_http() {
  local url="$1"
  local expect="${2:-}"
  local i=0
  while [[ $i -lt "$RETRIES" ]]; do
    if resp="$("${CURL[@]}" "$url" 2>/dev/null || true)"; then
      if [[ -z "$expect" || "$resp" == *"$expect"* ]]; then
        echo "$resp"
        return 0
      fi
    fi
    i=$((i + 1))
    sleep "$DELAY"
  done
  return 1
}

if "${CURL[@]}" "${BASE}/health" >/dev/null 2>&1; then
  log_ok "LAN /health reachable"
else
  log_fail "LAN /health not reachable at ${BASE}/health"
fi

if health_json="$(wait_http "${BASE}/health" '"ok"')" 2>/dev/null; then
  log_ok "Bridge health JSON ok (${health_json})"
else
  log_fail "Bridge /health did not return ok=true after $((RETRIES * DELAY))s"
fi

if wait_http "${BASE}/" '<html' >/dev/null 2>&1 || wait_http "${BASE}/" '<!DOCTYPE html' >/dev/null 2>&1; then
  log_ok "Dashboard HTML served at ${BASE}/"
else
  log_fail "Dashboard HTML not found at ${BASE}/"
fi

if wait_http "${BASE}/health/stack" '"services"' >/dev/null 2>&1; then
  log_ok "Stack health endpoint OK"
else
  log_fail "/health/stack probe failed"
fi

LOGIN_USER="${OFDD_OPERATOR_USER:-}"
LOGIN_PASS="${OFDD_OPERATOR_PASSWORD:-}"
if [[ -z "$LOGIN_USER" || -z "$LOGIN_PASS" ]] && [[ -f "$AUTH_ENV" ]]; then
  # shellcheck disable=SC1090
  set -a && source "$AUTH_ENV" && set +a
  LOGIN_USER="${OFDD_OPERATOR_USER:-}"
  LOGIN_PASS="${OFDD_OPERATOR_PASSWORD:-}"
fi

if [[ -n "$LOGIN_USER" && -n "$LOGIN_PASS" ]]; then
  login_body="$(python3 -c 'import json,sys; print(json.dumps({"username":sys.argv[1],"password":sys.argv[2]}))' "$LOGIN_USER" "$LOGIN_PASS")"
  login_resp="$(
    curl -fsS --connect-timeout 5 --max-time 20 -k \
      -X POST "${BASE}/api/auth/login" \
      -H 'Content-Type: application/json' \
      -d "$login_body" \
      2>/dev/null || true
  )"
  if [[ "$login_resp" == *'"token"'* ]]; then
    log_ok "Auth login OK for user ${LOGIN_USER}"
  else
    log_fail "Auth login failed for user ${LOGIN_USER}"
  fi
else
  log_ok "Auth login probe skipped (no credentials in env or ${AUTH_ENV})"
fi

if command -v ssh >/dev/null 2>&1; then
  units=(caddy openfdd-bridge openfdd-bacnet-commission)
  for unit in "${units[@]}"; do
    state="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "${SSH_USER}@${HOST}" "systemctl is-active ${unit}" 2>/dev/null || echo missing)"
    if [[ "$state" == "active" ]]; then
      log_ok "systemd ${unit} active"
    else
      log_fail "systemd ${unit} state=${state}"
    fi
  done
else
  log_ok "SSH probe skipped (no ssh client)"
fi

echo "---"
if [[ "$FAILURES" -gt 0 ]]; then
  echo "Post-deploy check FAILED (${FAILURES} issue(s))" >&2
  exit 1
fi
echo "Post-deploy check PASSED for ${HOST}"
exit 0
