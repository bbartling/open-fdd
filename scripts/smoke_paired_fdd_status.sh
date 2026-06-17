#!/usr/bin/env bash
# Read-only smoke status — safe for Cursor agents (no attach, no wait).
set -euo pipefail

MODE="short"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tryout|--short|--standard|--overnight) MODE="${1#--}"; shift ;;
    --mode) MODE="${2:-short}"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--mode short|standard|overnight|tryout]"
      exit 0
      ;;
    *) shift ;;
  esac
done

STATUS="/tmp/paired_fdd_smoke_${MODE}.status.json"
PIDFILE="/tmp/paired_fdd_smoke_${MODE}.pid"

if [[ ! -f "$STATUS" ]]; then
  echo "No status file: $STATUS (smoke not started?)"
  exit 2
fi

python3 - <<'PY' "$STATUS" "$PIDFILE"
import json, sys
from pathlib import Path
status_path, pidfile = Path(sys.argv[1]), Path(sys.argv[2])
s = json.loads(status_path.read_text())
pid = pidfile.read_text().strip() if pidfile.is_file() else "?"
running = False
if pid and pid != "?":
    try:
        running = Path(f"/proc/{pid}").exists()
    except OSError:
        running = False
print(f"mode={s.get('mode')} elapsed={s.get('elapsed_minutes')}/{s.get('duration_minutes')}m pass={s.get('pass')} pass_so_far={s.get('pass_so_far')}")
print(f"phase={s.get('phase')} toggle={s.get('toggle')} pid={pid} running={running}")
bench = s.get("bench") or {}
acme = s.get("acme") or {}
if isinstance(bench, dict) and bench.get("smoke_flagged"):
    print(f"bench_smoke={bench.get('smoke_flagged')}")
if isinstance(acme, dict) and acme.get("smoke_flagged"):
    print(f"acme_smoke={acme.get('smoke_flagged')}")
for issue in (s.get("issues") or [])[:5]:
    print(f"issue: {issue}")
if s.get("finished_at"):
    print(f"finished_at={s.get('finished_at')}")
    sys.exit(0 if s.get("pass") else 1)
sys.exit(0)
PY
