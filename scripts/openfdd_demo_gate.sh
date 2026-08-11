#!/usr/bin/env bash
# Refuse to print a Caddy login URL until the running web bundle matches
# what the agent claims the user will see.
#
#   ./scripts/openfdd_demo_gate.sh --local-web --marker overview-vibe19-oracle
#   ./scripts/openfdd_demo_gate.sh --ghcr-web   # published tip only
#
# Exit 0 prints the auth URL. Exit 1 prints GATE FAIL — do not hand out the link.
set -euo pipefail

MODE=""
MARKER=""
WEB_NAME="${OPENFDD_WEB_CONTAINER:-openfdd-react-web-1}"
URL="${OPENFDD_DEMO_AUTH_URL:-http://127.0.0.1/auth}"
LOCAL_INDEX="${OPENFDD_CADDY_INDEX_URL:-http://127.0.0.1/}"

usage() {
  cat <<'EOF'
Usage: openfdd_demo_gate.sh --local-web [--marker NAME] | --ghcr-web

--local-web   Unmerged frontend. Web image must NOT be ghcr.io/*.
              Bind-mount or local tag required. Optional --marker must appear
              in http://127.0.0.1/ (data-build / openfdd-web-build).
--ghcr-web    Merged + published only. Running web must be newest-by-OCI-created
              (scripts/ghcr_newest_by_created.py openfdd-web), not :nightly by name.
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

if ! docker inspect "$WEB_NAME" >/dev/null 2>&1; then
  echo "GATE FAIL: container $WEB_NAME is not running" >&2
  exit 1
fi

IMG="$(docker inspect "$WEB_NAME" --format '{{.Config.Image}}')"
BINDS="$(docker inspect "$WEB_NAME" --format '{{json .HostConfig.Binds}}')"
HTML="$(curl -fsS "$LOCAL_INDEX" || true)"

fail() {
  echo "GATE FAIL: $*" >&2
  echo "  Image=$IMG" >&2
  echo "  Binds=$BINDS" >&2
  echo "Do not paste $URL. Fix serve first." >&2
  exit 1
}

if [[ "$MODE" == local ]]; then
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

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NEWEST="$("$ROOT/scripts/ghcr_newest_by_created.py" --json openfdd-web)"
NEWEST_TAG="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["tag"])' <<<"$NEWEST")"
NEWEST_IMG="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["image"])' <<<"$NEWEST")"
case "$IMG" in
  "ghcr.io/bbartling/openfdd-web:$NEWEST_TAG"|"$NEWEST_IMG") ;;
  *:nightly|*:latest)
    fail "running $IMG but newest-by-created is $NEWEST_IMG — do not demo :nightly by name"
    ;;
  *)
    fail "running $IMG; newest published openfdd-web is $NEWEST_IMG"
    ;;
esac
echo "GATE OK: GHCR web is newest-by-OCI-created ($IMG)"
echo "$URL"
