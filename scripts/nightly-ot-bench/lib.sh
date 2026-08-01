#!/usr/bin/env bash
# Shared helpers for nightly OT bench gates (post–Phase-2 React + fieldbus).
# shellcheck disable=SC2034

NIGHTLY_OT_BENCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$NIGHTLY_OT_BENCH_DIR/../.." && pwd)"

load_bench_env() {
  local example="$NIGHTLY_OT_BENCH_DIR/bench.env.example"
  local localf="$NIGHTLY_OT_BENCH_DIR/bench.env.local"
  if [[ -f "$ROOT/.env" ]]; then
    # shellcheck disable=SC1091
    set -a && source "$ROOT/.env" && set +a
  fi
  if [[ -f "$localf" ]]; then
    # shellcheck disable=SC1090
    set -a && source "$localf" && set +a
  elif [[ -f "$example" ]]; then
    echo "WARN: no bench.env.local — sourcing bench.env.example (edit OT IPs for real LAN)" >&2
    # shellcheck disable=SC1090
    set -a && source "$example" && set +a
  fi

  FIELDBUS_BASE="${FIELDBUS_BASE:-http://127.0.0.1:8081}"
  CENTRAL_BASE="${CENTRAL_BASE:-http://127.0.0.1:8080}"
  UI_BASE="${UI_BASE:-http://127.0.0.1:3000}"
  KEY="${OPENFDD_FIELDBUS_API_KEY:-bench-demo-key-1234567890}"
  OPENFDD_SITE_ID="${OPENFDD_SITE_ID:-lab}"
  OPENFDD_EDGE_ID="${OPENFDD_EDGE_ID:-fieldbus-1}"
  BENCH_DEVICE="${BENCH_DEVICE:-5007}"
  HOSTED_DEVICE="${HOSTED_DEVICE:-599999}"
  WORKSPACE_DIR="${WORKSPACE_DIR:-workspace}"
  FEATHER_WAIT_SECS="${FEATHER_WAIT_SECS:-90}"
  export OPENFDD_REACT_UI="${OPENFDD_REACT_UI:-1}"
  export OPENFDD_UI_GENERATION_DEFAULT="${OPENFDD_UI_GENERATION_DEFAULT:-react}"
  # shellcheck source=scripts/openfdd_stack_lib.sh
  source "$ROOT/scripts/openfdd_stack_lib.sh"
  openfdd_stack_export_image_env
}

AUTH_HDR=()
auth_setup() {
  AUTH_HDR=()
  [[ -n "${KEY:-}" ]] && AUTH_HDR=(-H "Authorization: Bearer ${KEY}")
}

PASS=0
FAIL=0
SKIP=0
GREEN=$'\033[32m'
RED=$'\033[31m'
YELLOW=$'\033[33m'
BOLD=$'\033[1m'
DIM=$'\033[2m'
RST=$'\033[0m'

ok() { PASS=$((PASS + 1)); echo "${GREEN}PASS${RST} $*"; }
bad() { FAIL=$((FAIL + 1)); echo "${RED}FAIL${RST} $*" >&2; }
skip() { SKIP=$((SKIP + 1)); echo "${YELLOW}SKIP${RST} $*"; }
hdr() { echo; echo "${BOLD}== $* ==${RST}"; }

fb() {
  curl -fsS --max-time "${CURL_TIMEOUT:-45}" -H 'Content-Type: application/json' "${AUTH_HDR[@]}" "$@"
}
fb_long() {
  curl -fsS --max-time "${CURL_LONG_TIMEOUT:-240}" -H 'Content-Type: application/json' "${AUTH_HDR[@]}" "$@"
}
CENTRAL_AUTH_HDR=()
CENTRAL_AUTH_DONE=0
central_auth_setup() {
  # Acquire an admin JWT when central requires auth; no-op otherwise.
  CENTRAL_AUTH_HDR=()
  CENTRAL_AUTH_DONE=1
  local req tok
  req="$(curl -fsS --max-time 10 "$CENTRAL_BASE/api/auth/status" 2>/dev/null | jq -r '.auth_required // false' || echo false)"
  if [[ "$req" == "true" && -n "${OPENFDD_ADMIN_PASSWORD:-}" ]]; then
    tok="$(curl -fsS --max-time 15 -X POST "$CENTRAL_BASE/api/auth/login" \
      -H 'Content-Type: application/json' \
      -d "$(jq -nc --arg p "$OPENFDD_ADMIN_PASSWORD" '{username:"admin",password:$p}')" \
      | jq -r '.token // .access_token // empty' || true)"
    [[ -n "$tok" ]] && CENTRAL_AUTH_HDR=(-H "Authorization: Bearer $tok")
  fi
}

central() {
  if [[ "${CENTRAL_AUTH_DONE:-0}" != "1" ]]; then
    central_auth_setup
  fi
  curl -fsS --max-time "${CURL_TIMEOUT:-20}" "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" "$@"
}

jq_ok() {
  local label="$1" json="$2"
  shift 2
  if jq -e "$@" >/dev/null 2>&1 <<<"$json"; then
    ok "$label"
  else
    bad "$label"
  fi
}

approx() {
  # approx a b [eps] — float near-equal
  python3 - "$1" "$2" "${3:-0.5}" <<'PY'
import sys
a,b,eps=map(float,sys.argv[1:])
sys.exit(0 if abs(a-b)<=eps else 1)
PY
}

compose_files() {
  # Print -f / path pairs for react-ot (+ local OT overlay when present).
  openfdd_stack_compose_args react-ot
}

image_digest() {
  # Repo digest for a local image ref, or empty.
  docker image inspect "$1" --format '{{if .RepoDigests}}{{index .RepoDigests 0}}{{end}}' 2>/dev/null \
    | sed 's/^[^@]*@//' || true
}

resolve_tip_sha_tag() {
  # Prefer explicit OPENFDD_IMAGE_TAG=sha-…; else origin/master short SHA.
  local tag="${OPENFDD_IMAGE_TAG:-}"
  if [[ "$tag" == sha-* ]]; then
    echo "$tag"
    return 0
  fi
  if [[ "$tag" == "nightly" || -z "$tag" ]]; then
    local short
    short="$(git -C "$ROOT" rev-parse --short=7 origin/master 2>/dev/null \
      || git -C "$ROOT" rev-parse --short=7 HEAD)"
    echo "sha-${short}"
    return 0
  fi
  echo "$tag"
}

summary() {
  echo
  echo "${BOLD}Summary: ${GREEN}${PASS} passed${RST}, ${RED}${FAIL} failed${RST}, ${YELLOW}${SKIP} skipped${RST}"
  if [[ "$FAIL" -gt 0 ]]; then
    echo "${RED}GATE FAILED${RST}"
    return 1
  fi
  echo "${GREEN}GATE PASSED${RST}"
  return 0
}

artifact_dir() {
  local stamp
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  local dir="$ROOT/reports/nightly-ot-bench_${stamp}"
  mkdir -p "$dir"
  echo "$dir"
}

historian_snapshot() {
  # Print path|mtime|size lines for historian/feather artifacts
  local ws="$ROOT/${WORKSPACE_DIR}"
  find "$ws/data" \( -name '*.feather' -o -name '*.arrow' -o -name 'telemetry_pivot.jsonl' -o -path '*historian*' \) \
    -type f 2>/dev/null | sort | while read -r f; do
    stat -c '%n|%Y|%s' "$f" 2>/dev/null || stat -f '%N|%m|%z' "$f" 2>/dev/null
  done
}

web_asset_js() {
  # Dump SPA JS bundle from running web container or local WEB image into $1.
  local out="$1"
  local ctr
  ctr="$(docker ps --format '{{.Names}}' | grep -E 'openfdd-react-web' | head -1 || true)"
  if [[ -n "$ctr" ]]; then
    docker exec "$ctr" sh -c 'cat /usr/share/nginx/html/assets/*.js 2>/dev/null | head -c 8000000' >"$out" 2>/dev/null \
      && [[ -s "$out" ]] && return 0
  fi
  local img="${OPENFDD_WEB_IMAGE:-ghcr.io/bbartling/openfdd-web:${OPENFDD_IMAGE_TAG:-nightly}}"
  if docker image inspect "$img" >/dev/null 2>&1; then
    docker run --rm --entrypoint "" "$img" \
      sh -c 'cat /usr/share/nginx/html/assets/*.js 2>/dev/null | head -c 8000000' >"$out" 2>/dev/null \
      && [[ -s "$out" ]] && return 0
  fi
  return 1
}
