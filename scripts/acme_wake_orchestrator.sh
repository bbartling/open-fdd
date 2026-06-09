#!/usr/bin/env bash
# Acme FDD tuning + patch orchestrator for agent wake cycles.
#
# Schedule (default):
#   1. patch cycle (smoke → deploy → verify → tune → collect)
#   2. tuning wake × 3 (6 h apart)
#   3. patch cycle
#   4. tuning wake × 3 (6 h apart)
#   5. patch cycle (final)
#
#   ./scripts/acme_wake_orchestrator.sh run          # execute current phase
#   ./scripts/acme_wake_orchestrator.sh status
#   ./scripts/acme_wake_orchestrator.sh arm-sleep    # sleep 6h then emit wake sentinel
#   ACME_WAKE_TUNING_CYCLES=3 ACME_WAKE_PATCH_CYCLES=2 ./scripts/acme_wake_orchestrator.sh run
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STATE_DIR="${ACME_WAKE_STATE_DIR:-$ROOT/.acme_wake}"
STATE_FILE="$STATE_DIR/state.json"
SLEEP_HOURS="${ACME_WAKE_SLEEP_HOURS:-6}"
TUNING_PER_BLOCK="${ACME_WAKE_TUNING_CYCLES:-3}"
PATCH_CYCLES="${ACME_WAKE_PATCH_CYCLES:-2}"
SENTINEL="${ACME_WAKE_SENTINEL:-AGENT_ACME_WAKE}"

mkdir -p "$STATE_DIR"

now_iso() { date -u +%Y-%m-%dT%H:%M:%SZ; }
now_epoch() { date -u +%s; }

init_state() {
  if [[ ! -f "$STATE_FILE" ]]; then
    python3 - <<PY
import json
from pathlib import Path
p = Path("$STATE_FILE")
p.write_text(json.dumps({
    "started_at": "$(now_iso)",
    "phase": "patch",
    "patch_num": 1,
    "tuning_in_block": 0,
    "patches_done": 0,
    "tuning_wakes_done": 0,
    "last_run_at": "",
    "last_result": "",
    "history": [],
}, indent=2))
PY
  fi
}

read_state() { python3 -c "import json; print(json.load(open('$STATE_FILE')))"; }

save_note() {
  local note="$1"
  python3 - <<PY
import json
from pathlib import Path
p = Path("$STATE_FILE")
s = json.loads(p.read_text())
s["last_run_at"] = "$(now_iso)"
s["last_result"] = """$note"""
s.setdefault("history", []).append({"at": "$(now_iso)", "note": """$note"""})
p.write_text(json.dumps(s, indent=2))
PY
}

advance_state() {
  python3 - <<PY
import json
from pathlib import Path

tuning_per = int("$TUNING_PER_BLOCK")
patch_total = 1 + int("$PATCH_CYCLES")  # initial patch + N more after tuning blocks

p = Path("$STATE_FILE")
s = json.loads(p.read_text())
phase = s.get("phase", "patch")
patch_num = int(s.get("patch_num") or 1)
tuning_in = int(s.get("tuning_in_block") or 0)

if phase == "patch":
    s["patches_done"] = int(s.get("patches_done") or 0) + 1
    if patch_num >= patch_total:
        s["phase"] = "complete"
    else:
        s["phase"] = "tuning"
        s["tuning_in_block"] = 0
elif phase == "tuning":
    tuning_in += 1
    s["tuning_wakes_done"] = int(s.get("tuning_wakes_done") or 0) + 1
    s["tuning_in_block"] = tuning_in
    if tuning_in >= tuning_per:
        s["phase"] = "patch"
        s["patch_num"] = patch_num + 1
        s["tuning_in_block"] = 0

p.write_text(json.dumps(s, indent=2))
print(json.dumps(s))
PY
}

run_patch_cycle() {
  echo "==> patch cycle smokes"
  python3 -m pytest open_fdd/tests/arrow_runtime open_fdd/tests/faults tests/test_no_pandas_edge_fdd.py \
    tests/workspace_bridge/test_fdd_brick_column_sweep.py -q

  if [[ -f infra/ansible/secrets/acme.env.local ]]; then
    # shellcheck disable=SC1091
    source infra/ansible/secrets/acme.env.local
    echo "==> Acme operational verify"
    ./infra/ansible/scripts/acme_operational_verify.sh --host "${ACME_SSH_HOST}"
  else
    echo "WARN: no acme.env.local — skip edge verify"
  fi
}

run_tuning_collect() {
  echo "==> portfolio collect + FDD audit"
  python3 scripts/portfolio_collect.py --json 2>&1 | tail -30

  if [[ -f infra/ansible/secrets/acme.env.local ]]; then
    # shellcheck disable=SC1091
    source infra/ansible/secrets/acme.env.local
    python3 <<'PY'
import json, os, urllib.request
base = f"http://{os.environ['ACME_SSH_HOST']}"
login = urllib.request.Request(
    f"{base}/api/auth/login",
    data=json.dumps({"username": os.environ["ACME_INTEGRATOR_USER"],
                      "password": os.environ["ACME_INTEGRATOR_PASSWORD"]}).encode(),
    headers={"Content-Type": "application/json"}, method="POST",
)
with urllib.request.urlopen(login, timeout=30) as r:
    token = json.load(r).get("token")
hdr = {"Authorization": f"Bearer {token}"}
for path, method, body in [
    ("/api/building-agent/checkin", "POST", {"site_id": "acme", "run_fdd_batch": True}),
    ("/api/building-agent/tuning-brief?site_id=acme&window_minutes=180", "GET", None),
]:
    req = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(body).encode() if body else None,
        headers={**hdr, **({"Content-Type": "application/json"} if body else {})},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    print(path, json.dumps(d, indent=2)[:2500])
PY
  fi
}

cmd_status() {
  init_state
  echo "state: $STATE_FILE"
  read_state | python3 -m json.tool
}

cmd_arm_sleep() {
  local secs=$((SLEEP_HOURS * 3600))
  echo "Arming ${SLEEP_HOURS}h sleep (${secs}s) → sentinel ${SENTINEL}"
  (
    sleep "$secs"
    echo "${SENTINEL} $(now_iso) phase=$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('phase','?'))")"
  ) &
  echo "sleep_pid=$!"
}

cmd_run() {
  init_state
  local phase patch_num
  phase="$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('phase','patch'))")"
  patch_num="$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('patch_num',1))")"

  echo "acme_wake: phase=$phase patch_num=$patch_num"
  case "$phase" in
    patch)
      run_patch_cycle
      save_note "patch $patch_num verify OK"
      ;;
    tuning)
      run_tuning_collect
      save_note "tuning wake collect OK"
      ;;
    complete)
      echo "acme_wake: schedule complete"
      exit 0
      ;;
    *)
      echo "unknown phase: $phase" >&2
      exit 1
      ;;
  esac

  advance_state | python3 -m json.tool
  local next_phase
  next_phase="$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('phase','?'))")"
  if [[ "$next_phase" != "complete" ]]; then
    cmd_arm_sleep
  fi
  echo "${SENTINEL}_DONE $(now_iso) next=$next_phase"
}

case "${1:-}" in
  run) cmd_run ;;
  status) cmd_status ;;
  arm-sleep) cmd_arm_sleep ;;
  -h|--help)
    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
    ;;
  *)
    echo "Usage: $0 {run|status|arm-sleep}" >&2
    exit 1
    ;;
esac
