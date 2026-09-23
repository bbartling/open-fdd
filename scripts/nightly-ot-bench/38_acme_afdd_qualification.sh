#!/usr/bin/env bash
# Gate 38 — ACME continuous AFDD qualification (primary live AFDD SoT).
# Synthetic-59 flood remains gate 19; this gate proves ACME 24h lookback cycles.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
OUT="$ART/38_acme_afdd_qualification.json"
SUMMARY="$ART/38_acme_afdd_qualification.md"

if [[ "${RAILWAY_ONLY:-0}" != "1" && "${ACME_AFDD_QUAL:-0}" != "1" ]]; then
  echo "SKIP: set RAILWAY_ONLY=1 or ACME_AFDD_QUAL=1" | tee "$SUMMARY"
  echo '{"ok":false,"status":"SKIPPED","reason":"not railway/acme qual window"}' >"$OUT"
  exit 0
fi

BUILDING="${OPENFDD_ACME_AFDD_BUILDING:-ACME}"
MAX_WALL="${OPENFDD_ACME_AFDD_MAX_WALL_SECS:-600}"
EXPECT_INTERVAL="${OPENFDD_ACME_AFDD_EXPECT_INTERVAL_MINUTES:-1440}"
EXPECT_LOOKBACK_HOURS="${OPENFDD_ACME_AFDD_EXPECT_LOOKBACK_HOURS:-24}"

python3 - <<'PY' "$CENTRAL_BASE" "$OUT" "$SUMMARY" "$BUILDING" "$MAX_WALL" "$EXPECT_INTERVAL" "$EXPECT_LOOKBACK_HOURS"
import json, os, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone

base, out, summary, building, max_wall, expect_interval, expect_lb_h = sys.argv[1:8]
max_wall = int(max_wall)
expect_interval = int(expect_interval)
expect_lb_h = float(expect_lb_h)
slack_h = 5.0 / 60.0  # 5 minutes

def http(method, path, token=None, body=None, timeout=120):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode() or "{}")

def parse_dt(raw):
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    s = str(raw).replace("Z", "+00:00")
    return datetime.fromisoformat(s)

report = {
    "ok": False,
    "building_id": building,
    "hub": base,
    "checks": {},
    "budgets": {
        "max_wall_secs": max_wall,
        "expect_interval_minutes": expect_interval,
        "expect_lookback_hours": expect_lb_h,
        "window_slack_hours": slack_h,
    },
}

admin_user = os.environ.get("OPENFDD_ADMIN_USER", "admin")
admin_pass = os.environ.get("OPENFDD_ADMIN_PASSWORD", "")
token = (os.environ.get("OPENFDD_ADMIN_TOKEN") or os.environ.get("OPENFDD_BEARER_TOKEN") or "").strip() or None
if not token:
    if not admin_pass:
        report["error"] = "need OPENFDD_ADMIN_TOKEN or OPENFDD_ADMIN_PASSWORD"
        open(out, "w").write(json.dumps(report, indent=2))
        open(summary, "w").write("# Gate 38 FAIL\n\nmissing admin auth\n")
        raise SystemExit(1)
    _, login = http("POST", "/api/auth/login", body={"username": admin_user, "password": admin_pass})
    token = login.get("access_token") or login.get("token")

# A. Config truth
_, status = http("GET", "/api/afdd/scheduler/status", token=token)
cfg = status.get("config") or {}
mode = (cfg.get("mode") or "").lower()
interval = int(cfg.get("interval_minutes") or 0)
lb_value = int(cfg.get("lookback_value") or 0)
lb_unit = (cfg.get("lookback_unit") or "").lower()
timer_scope = status.get("timer_scope") or ""
lookback_hours = None
if lb_unit in ("hour", "hours"):
    lookback_hours = float(lb_value)
elif lb_unit in ("day", "days"):
    lookback_hours = float(lb_value) * 24.0
elif lb_unit in ("minute", "minutes"):
    lookback_hours = float(lb_value) / 60.0

cfg_ok = (
    mode == "continuous"
    and interval == expect_interval
    and lookback_hours is not None
    and abs(lookback_hours - expect_lb_h) < 0.01
    and timer_scope.upper() == building.upper()
)
report["checks"]["config"] = {
    "ok": cfg_ok,
    "mode": mode,
    "interval_minutes": interval,
    "lookback_value": lb_value,
    "lookback_unit": lb_unit,
    "lookback_hours": lookback_hours,
    "timer_scope": timer_scope,
}
if not cfg_ok:
    report["error"] = (
        f"config truth failed: want continuous/{expect_interval}min/"
        f"{expect_lb_h}h scope={building}; got mode={mode} interval={interval} "
        f"lookback={lb_value}{lb_unit} scope={timer_scope}"
    )
    open(out, "w").write(json.dumps(report, indent=2))
    open(summary, "w").write(f"# Gate 38 FAIL\n\n{report['error']}\n")
    raise SystemExit(1)

# B. Live cycle on ACME
t0 = time.time()
try:
    st, body = http(
        "POST",
        "/api/afdd/scheduler/run-now",
        token=token,
        body={"building_id": building},
        timeout=max_wall,
    )
except urllib.error.HTTPError as e:
    report["error"] = f"run-now HTTP {e.code}: {e.reason}"
    report["checks"]["run_now"] = {"ok": False, "http": e.code}
    open(out, "w").write(json.dumps(report, indent=2))
    open(summary, "w").write(f"# Gate 38 FAIL\n\n{report['error']}\n")
    raise SystemExit(1)
except Exception as e:
    report["error"] = f"run-now failed: {e}"
    report["checks"]["run_now"] = {"ok": False, "error": str(e)}
    open(out, "w").write(json.dumps(report, indent=2))
    open(summary, "w").write(f"# Gate 38 FAIL\n\n{report['error']}\n")
    raise SystemExit(1)

elapsed = time.time() - t0
cycle = body.get("cycle") or body
ok = bool(body.get("ok") is True or cycle.get("ok") is True)
scope = str(cycle.get("scope") or "")
run_id = cycle.get("run_id")
start = parse_dt(cycle.get("start_utc"))
end = parse_dt(cycle.get("end_utc"))
window_hours = None
if start and end:
    window_hours = (end - start).total_seconds() / 3600.0

report["checks"]["run_now"] = {
    "ok": ok and scope.upper() == building.upper() and elapsed <= max_wall,
    "http": st,
    "elapsed_secs": round(elapsed, 3),
    "scope": scope,
    "run_id": run_id,
    "status": cycle.get("status"),
    "rules_succeeded": cycle.get("rules_succeeded"),
    "rules_failed": cycle.get("rules_failed"),
    "rules_skipped": cycle.get("rules_skipped"),
    "error": cycle.get("error"),
}
if not report["checks"]["run_now"]["ok"]:
    report["error"] = (
        f"ACME run-now failed ok={ok} scope={scope} elapsed={elapsed:.1f}s "
        f"err={cycle.get('error')}"
    )
    open(out, "w").write(json.dumps(report, indent=2))
    open(summary, "w").write(f"# Gate 38 FAIL\n\n{report['error']}\n")
    raise SystemExit(1)

# C. Lookback bound
bound_ok = (
    window_hours is not None
    and window_hours <= expect_lb_h + slack_h
    and window_hours < 7.0 * 24.0
)
report["checks"]["lookback_bound"] = {
    "ok": bound_ok,
    "start_utc": cycle.get("start_utc"),
    "end_utc": cycle.get("end_utc"),
    "window_hours": window_hours,
}
if not bound_ok:
    report["error"] = (
        f"lookback not bounded: window_hours={window_hours} "
        f"(expect <= {expect_lb_h + slack_h})"
    )
    open(out, "w").write(json.dumps(report, indent=2))
    open(summary, "w").write(f"# Gate 38 FAIL\n\n{report['error']}\n")
    raise SystemExit(1)

# D. Durable artifacts via recent_cycles
_, status2 = http("GET", "/api/afdd/scheduler/status", token=token)
recent = status2.get("recent_cycles") or []
top = recent[0] if recent else {}
art_ok = (
    str(top.get("run_id") or "") == str(run_id)
    and str(top.get("scope") or "").upper() == building.upper()
    and bool(top.get("ok") is True)
)
report["checks"]["durable_cycle"] = {
    "ok": art_ok,
    "recent_top_run_id": top.get("run_id"),
    "recent_top_scope": top.get("scope"),
    "recent_top_ok": top.get("ok"),
    "recent_count": len(recent),
}
if not art_ok:
    report["error"] = "recent_cycles missing matching ACME ok cycle for run_id"
    open(out, "w").write(json.dumps(report, indent=2))
    open(summary, "w").write(f"# Gate 38 FAIL\n\n{report['error']}\n")
    raise SystemExit(1)

# E. Efficiency + executed-rule proof (not all-skip / empty cycle theater)
succ = int(cycle.get("rules_succeeded") or 0)
fail = int(cycle.get("rules_failed") or 0)
skip = int(cycle.get("rules_skipped") or 0)
executed = succ + fail
eff_ok = (
    window_hours is not None
    and window_hours <= expect_lb_h + 0.1
    and executed > 0
)
report["checks"]["efficiency"] = {
    "ok": eff_ok,
    "elapsed_secs": round(elapsed, 3),
    "window_hours": window_hours,
    "rules_succeeded": succ,
    "rules_failed": fail,
    "rules_skipped": skip,
    "rules_executed": executed,
}
if executed == 0:
    report["error"] = (
        "AFDD cycle executed zero rules (all-skipped or empty) — not useful qualification"
    )
    open(out, "w").write(json.dumps(report, indent=2))
    open(summary, "w").write(f"# Gate 38 FAIL\n\n{report['error']}\n")
    raise SystemExit(1)
if not eff_ok:
    report["error"] = f"efficiency check failed window_hours={window_hours} executed={executed}"
    open(out, "w").write(json.dumps(report, indent=2))
    open(summary, "w").write(f"# Gate 38 FAIL\n\n{report['error']}\n")
    raise SystemExit(1)

report["ok"] = True
report["window_hours"] = window_hours
report["elapsed_secs"] = round(elapsed, 3)

open(out, "w").write(json.dumps(report, indent=2))
open(summary, "w").write(
    f"""# Gate 38 PASS — ACME continuous AFDD qual

- building: `{building}`
- config: continuous / {interval} min / {lookback_hours}h lookback / timer_scope={timer_scope}
- cycle run_id: `{run_id}`
- window_hours: {window_hours}
- elapsed_secs: {elapsed:.1f}
- rules_succeeded/failed/skipped: {succ}/{fail}/{skip} (executed={executed})
"""
)
print(summary, "PASS", flush=True)
raise SystemExit(0)
PY
