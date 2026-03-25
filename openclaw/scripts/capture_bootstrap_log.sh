#!/usr/bin/env bash
# Run from open-fdd repo root: openclaw/scripts/capture_bootstrap_log.sh [args to bootstrap...]
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"
mkdir -p openclaw/logs
ts="$(date +%F_%H-%M-%S)"
log="openclaw/logs/bootstrap-test-${ts}.txt"
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  # shellcheck source=/dev/null
  source "$REPO_ROOT/.venv/bin/activate"
fi
echo "Logging to $log" | tee "$log"
./scripts/bootstrap.sh "$@" 2>&1 | tee -a "$log"
echo "Done. Log: $log"
