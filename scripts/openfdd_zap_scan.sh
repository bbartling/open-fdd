#!/usr/bin/env bash
# OWASP ZAP baseline — one target (supports HTTPS self-signed via OPENFDD_ZAP_TLS_INSECURE=1).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

TARGET="${OPENFDD_ZAP_TARGET:-http://127.0.0.1:8080}"
LABEL="${OPENFDD_ZAP_LABEL:-default}"
AUTH_ENV="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
OUT_DIR="${OPENFDD_ZAP_OUT_DIR:-$ROOT/workspace/logs/zap_${LABEL}_$(date -u +%Y%m%dT%H%M%SZ)}"
ZAP_IMAGE="${OPENFDD_ZAP_IMAGE:-ghcr.io/zaproxy/zaproxy:stable}"
MAX_MINS="${OPENFDD_ZAP_MAX_MINUTES:-10}"
FAIL_ON_WARN="${OPENFDD_ZAP_FAIL_ON_WARN:-0}"
TLS_INSECURE="${OPENFDD_ZAP_TLS_INSECURE:-0}"

[[ "$TARGET" == https://* ]] && TLS_INSECURE="${OPENFDD_ZAP_TLS_INSECURE:-1}"

mkdir -p "$OUT_DIR"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [$LABEL] $*" | tee -a "$OUT_DIR/zap.log"; }

CURL_EXTRA=()
[[ "$TLS_INSECURE" == "1" || "$TARGET" == https://* ]] && CURL_EXTRA=(-k)

if ! curl "${CURL_EXTRA[@]}" -fsS -o /dev/null -m 15 "${TARGET}/" 2>/dev/null; then
  log "ERROR: dashboard not reachable at ${TARGET}/"
  exit 1
fi

TOKEN=""
if [[ -z "${OPENFDD_ZAP_AUTH_HEADER:-}" ]] && [[ -f "$AUTH_ENV" ]]; then
  TOKEN="$(openfdd_auth_login_token "$TARGET" "$AUTH_ENV" integrator 2>/dev/null || true)"
  [[ -n "$TOKEN" ]] && OPENFDD_ZAP_AUTH_HEADER="Authorization: Bearer ${TOKEN}"
fi

CONFIG_FILE="$OUT_DIR/zap_config.conf"
: >"$CONFIG_FILE"
if [[ -n "${OPENFDD_ZAP_AUTH_HEADER:-}" ]]; then
  log "ZAP JWT replacer for authenticated /api/* routes"
  cat >>"$CONFIG_FILE" <<EOF
replacer.full_list(0).description=OpenFDD JWT
replacer.full_list(0).enabled=true
replacer.full_list(0).matchtype=REQ_HEADER
replacer.full_list(0).matchstr=
replacer.full_list(0).regex=false
replacer.full_list(0).replacement=${OPENFDD_ZAP_AUTH_HEADER}
EOF
fi

if [[ "$TLS_INSECURE" == "1" ]]; then
  cat >>"$CONFIG_FILE" <<'EOF'
# Self-signed / lab TLS (Caddy caddy-tls profile)
connection.ssl.trustAll=true
network.ssl.trustAll=true
EOF
fi

log "Pull ${ZAP_IMAGE}"
docker pull "$ZAP_IMAGE" >>"$OUT_DIR/zap.log" 2>&1 || true

log "ZAP baseline → ${TARGET} label=${LABEL} tls_insecure=${TLS_INSECURE} (max ${MAX_MINS}m)"
ZAP_ARGS=(
  zap-baseline.py
  -t "$TARGET"
  -J "$OUT_DIR/zap_report.json"
  -r "$OUT_DIR/zap_report.html"
  -w "$OUT_DIR/zap_report.md"
  -m "$MAX_MINS"
  -I
)
[[ -f "$CONFIG_FILE" && -s "$CONFIG_FILE" ]] && ZAP_ARGS+=(-z "$CONFIG_FILE")

set +e
docker run --rm --network host \
  -v "$OUT_DIR:/zap/wrk:rw" \
  "$ZAP_IMAGE" "${ZAP_ARGS[@]}" 2>&1 | tee -a "$OUT_DIR/zap_baseline.log"
ZAP_EXIT=${PIPESTATUS[0]}
set -e

jq -nc \
  --arg target "$TARGET" \
  --arg label "$LABEL" \
  --arg out "$OUT_DIR" \
  --argjson exit "$ZAP_EXIT" \
  --argjson tls_insecure "$([[ "$TLS_INSECURE" == 1 ]] && echo true || echo false)" \
  --argjson fail_on_warn "$([[ "$FAIL_ON_WARN" == 1 ]] && echo true || echo false)" \
  '{target:$target,label:$label,tls_insecure:$tls_insecure,artifact_dir:$out,zap_exit_code:$exit,
    pass:($exit==0 or ($exit==2 and ($fail_on_warn|not)))}' \
  >"$OUT_DIR/zap_result.json"

log "ZAP exit=$ZAP_EXIT artifacts=$OUT_DIR"

if [[ "$ZAP_EXIT" -eq 0 ]]; then exit 0; fi
if [[ "$ZAP_EXIT" -eq 2 && "$FAIL_ON_WARN" != "1" ]]; then
  log "WARN: ZAP warnings only"
  exit 0
fi
exit 1
