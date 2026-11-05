#!/usr/bin/env bash
# Refuse to print a demo login URL until the running product UI matches what
# the agent claims the user will see.
#
#   ./scripts/openfdd_demo_gate.sh --local-web --marker overview-vibe19-oracle
#   ./scripts/openfdd_demo_gate.sh --ghcr-web   # published central + static /app/ only
#
# Exit 0 prints the auth URL. Exit 1 prints GATE FAIL — do not hand out the link.
set -euo pipefail

MODE=""
MARKER=""
WEB_NAME="${OPENFDD_WEB_CONTAINER:-openfdd-react-web-1}"
CENTRAL_NAME="${OPENFDD_CENTRAL_CONTAINER:-}"
API_BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
URL="${OPENFDD_DEMO_AUTH_URL:-http://127.0.0.1/auth}"
LOCAL_INDEX="${OPENFDD_CADDY_INDEX_URL:-http://127.0.0.1/}"

usage() {
  cat <<'EOF'
Usage: openfdd_demo_gate.sh --local-web [--marker NAME] | --ghcr-web

--local-web   Unmerged archived React SPA (rollback web container or Caddy).
              Web image must NOT be ghcr.io/* unless bind-mounted local dist.
              Optional --marker must appear in http://127.0.0.1/ (data-build).
--ghcr-web    Merged + published portal stack: running openfdd-central must be
              newest-by-OCI-created (scripts/ghcr_newest_by_created.py
              openfdd-central), static product UI at /app/ must answer with CSP
              and core assets (not :nightly by name). No separate web container.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local-web) MODE=local; shift ;;
    --ghcr-web) MODE=ghcr; shift ;;
    --marker) MARKER="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown arg $1" >&2; usage; exit 2 ;;
  esac
done

if [[ -z "$MODE" ]]; then
  usage >&2
  exit 2
fi

fail() {
  echo "GATE FAIL: $*" >&2
  echo "Do not paste $URL. Fix serve first." >&2
  exit 1
}

resolve_central_container() {
  if [[ -n "$CENTRAL_NAME" ]] && docker inspect "$CENTRAL_NAME" >/dev/null 2>&1; then
    printf '%s' "$CENTRAL_NAME"
    return 0
  fi
  local project img
  project="$(docker ps --filter 'label=com.docker.compose.service=central' --format '{{.Label "com.docker.compose.project"}}' | head -1)"
  if [[ -n "$project" ]]; then
    img="$(docker ps --filter "label=com.docker.compose.project=$project" --filter 'label=com.docker.compose.service=central' --format '{{.Names}}' | head -1)"
    [[ -n "$img" ]] && printf '%s' "$img" && return 0
  fi
  img="$(docker ps --format '{{.Names}}' | grep -E '(^|-)central(-|_|$|[0-9]+$)' | head -1 || true)"
  [[ -n "$img" ]] && printf '%s' "$img"
}

assert_static_app() {
  local base="${API_BASE%/}"
  local csp code path
  csp="$(curl -fsS --max-time 15 -I "$base/app/" | tr -d '\r' | awk -F': ' 'tolower($1)=="content-security-policy"{print $2; exit}' || true)"
  [[ -n "$csp" ]] || fail "missing Content-Security-Policy on $base/app/"
  case "$csp" in
    *unsafe-inline*|*unsafe-eval*) fail "CSP on /app/ must not allow unsafe-inline or unsafe-eval" ;;
  esac
  for path in /app/ /app/assets/js/app.js /app/assets/vendor/echarts.esm.min.js; do
    code="$(curl -fsS --max-time 15 -o /dev/null -w '%{http_code}' "$base$path" || echo 000)"
    [[ "$code" == "200" ]] || fail "GET $base$path HTTP $code"
  done
}

if [[ "$MODE" == "local" ]]; then
  if ! docker inspect "$WEB_NAME" >/dev/null 2>&1; then
    fail "container $WEB_NAME is not running (use --ghcr-web for central static /app/ only)"
  fi
  IMG="$(docker inspect "$WEB_NAME" --format '{{.Config.Image}}')"
  BINDS="$(docker inspect "$WEB_NAME" --format '{{json .HostConfig.Binds}}')"
  HTML="$(curl -fsS "$LOCAL_INDEX" || true)"
  case "$IMG" in
    ghcr.io/*) fail "web is GHCR ($IMG). Unmerged UI is not in that image." ;;
  esac
  if [[ "$BINDS" == "null" || "$BINDS" == "[]" ]]; then
    case "$IMG" in
      openfdd-web:*|*:local*|*:overview-*) ;;
      *) fail "no local bind-mount and image is not a local tag" ;;
    esac
  fi
  if [[ -n "$MARKER" ]] && ! grep -q "$MARKER" <<<"$HTML"; then
    fail "http://127.0.0.1/ missing data-build marker '$MARKER' (stale index.html)"
  fi
  echo "GATE OK: local Overview bundle (not GHCR)"
  echo "  Image=$IMG"
  echo "  Binds=$BINDS"
  echo "this is the local Overview bundle, not GHCR."
  echo "$URL"
  exit 0
fi

# --ghcr-web: static product UI on central (ADR-013); openfdd-web container is rollback-only.
CENTRAL_NAME="$(resolve_central_container || true)"
[[ -n "$CENTRAL_NAME" ]] || fail "no running openfdd-central container (portal stack required)"
if ! docker inspect "$CENTRAL_NAME" >/dev/null 2>&1; then
  fail "container $CENTRAL_NAME is not running"
fi
IMG="$(docker inspect "$CENTRAL_NAME" --format '{{.Config.Image}}')"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NEWEST="$("$ROOT/scripts/ghcr_newest_by_created.py" --json openfdd-central)"
NEWEST_TAG="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["tag"])' <<<"$NEWEST")"
NEWEST_IMG="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["image"])' <<<"$NEWEST")"
case "$IMG" in
  "ghcr.io/bbartling/openfdd-central:$NEWEST_TAG"|"$NEWEST_IMG") ;;
  *:nightly|*:latest)
    fail "running $IMG but newest-by-created is $NEWEST_IMG — do not demo :nightly by name"
    ;;
  *)
    fail "running $IMG; newest published openfdd-central is $NEWEST_IMG"
    ;;
esac

assert_static_app

echo "GATE OK: GHCR central is newest-by-OCI-created ($IMG); static /app/ verified"
echo "  Container=$CENTRAL_NAME"
echo "  API=$API_BASE/app/"
echo "$URL"
