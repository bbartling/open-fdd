#!/usr/bin/env bash
# Local + optional remote battery for bench device 5007 Arrow FDD, GHCR images, and prod Caddy.
#
#   ./infra/ansible/scripts/bench_5007_arrow_battery.sh
#   ./infra/ansible/scripts/bench_5007_arrow_battery.sh --host 127.0.0.1 --port 80
#   ./infra/ansible/scripts/bench_5007_arrow_battery.sh --ghcr-only
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/../../.." && pwd)"
cd "$ROOT"

HOST=""
PORT=""
GHCR_ONLY=0
FAILURES=0
TAG="${OPENFDD_IMAGE_TAG:-latest}"

log_ok() { printf '  OK   %s\n' "$*"; }
log_fail() { printf '  FAIL %s\n' "$*" >&2; FAILURES=$((FAILURES + 1)); }
log_info() { printf '  ..   %s\n' "$*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --ghcr-only) GHCR_ONLY=1; shift ;;
    -h|--help)
      sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

log_info "=== Pytest: bench 5007 Arrow FDD ==="
if python3 -m pytest tests/workspace_bridge/test_bench_5007_arrow_fdd.py -q --tb=short; then
  log_ok "bench 5007 Arrow FDD pytest"
else
  log_fail "bench 5007 Arrow FDD pytest"
fi

if [[ "$GHCR_ONLY" == "1" ]]; then
  :
else
  log_info "=== Pytest: full workspace_bridge ==="
  if python3 -m pytest tests/workspace_bridge/ -q --tb=line; then
    log_ok "workspace_bridge full suite"
  else
    log_fail "workspace_bridge full suite"
  fi

  log_info "=== Vitest: dashboard ==="
  if (cd workspace/dashboard && npm test -- --run 2>/dev/null); then
    log_ok "dashboard vitest"
  else
    log_fail "dashboard vitest"
  fi
fi

log_info "=== GHCR image manifests (Acme edge trio) ==="
for img in openfdd-bridge openfdd-commission openfdd-mcp-rag; do
  if docker manifest inspect "ghcr.io/bbartling/${img}:${TAG}" >/dev/null 2>&1; then
    log_ok "ghcr.io/bbartling/${img}:${TAG}"
  else
    log_fail "missing ghcr.io/bbartling/${img}:${TAG}"
  fi
done

if [[ -n "$HOST" ]]; then
  if [[ -n "$PORT" ]]; then
    BASE="http://${HOST}:${PORT}"
  else
    BASE="http://${HOST}"
  fi
  log_info "=== HTTP probes → ${BASE} ==="
  if curl -fsS --connect-timeout 5 --max-time 15 "${BASE}/health" | python3 -c '
import json,sys
d=json.load(sys.stdin)
assert d.get("ok") is True
v=d.get("openfdd_version") or ""
print(v)
'; then
    log_ok "/health reachable (openfdd_version in response)"
  else
    log_fail "/health ${BASE}/health"
  fi
fi

echo "---"
if [[ "$FAILURES" -gt 0 ]]; then
  echo "Bench 5007 battery FAILED (${FAILURES} issue(s))" >&2
  exit 1
fi
echo "Bench 5007 battery PASSED"
exit 0
