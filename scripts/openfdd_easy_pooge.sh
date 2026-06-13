#!/usr/bin/env bash
# Guarded Easy Pooge / edge reset — see workspace/api/openfdd_bridge/pooge_service.py
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DRY_RUN=1
CONFIRM=""
CLEAR_HISTORIAN=0
CLEAR_BACNET=0
CLEAR_MODEL=0
CLEAR_RULES=0
CLEAR_EXPORTS=0
LINUX_UPDATE=0
DOCKER_UPDATE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --confirm) CONFIRM="${2:?}"; DRY_RUN=0; shift 2 ;;
    --clear-historian) CLEAR_HISTORIAN=1; shift ;;
    --clear-bacnet) CLEAR_BACNET=1; shift ;;
    --clear-model) CLEAR_MODEL=1; shift ;;
    --clear-rules) CLEAR_RULES=1; shift ;;
    --clear-exports) CLEAR_EXPORTS=1; shift ;;
    --linux-update) LINUX_UPDATE=1; shift ;;
    --docker-update) DOCKER_UPDATE=1; shift ;;
    -h|--help)
      sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

if [[ "$DRY_RUN" == 0 && "$CONFIRM" != "RESET THIS EDGE" ]]; then
  echo "ERROR: --confirm must be exactly: RESET THIS EDGE" >&2
  exit 1
fi

export ROOT DRY_RUN CONFIRM CLEAR_HISTORIAN CLEAR_BACNET CLEAR_MODEL CLEAR_RULES CLEAR_EXPORTS LINUX_UPDATE DOCKER_UPDATE
export PYTHONPATH="${ROOT}/workspace/api:${PYTHONPATH:-}"

python3 - <<'PY'
import json
import os
import sys

from openfdd_bridge.pooge_service import PoogeRequest, preview_pooge, run_pooge

req = PoogeRequest(
    dry_run=bool(int(os.environ["DRY_RUN"])),
    confirmation=os.environ.get("CONFIRM", ""),
    clear_historian=bool(int(os.environ["CLEAR_HISTORIAN"])),
    clear_bacnet=bool(int(os.environ["CLEAR_BACNET"])),
    clear_model=bool(int(os.environ["CLEAR_MODEL"])),
    clear_rules=bool(int(os.environ["CLEAR_RULES"])),
    clear_exports=bool(int(os.environ["CLEAR_EXPORTS"])),
    linux_update=bool(int(os.environ["LINUX_UPDATE"])),
    docker_update=bool(int(os.environ["DOCKER_UPDATE"])),
)
out = preview_pooge(req) if req.dry_run else run_pooge(req)
print(json.dumps(out, indent=2))
sys.exit(0 if out.get("ok", True) else 1)
PY
