#!/usr/bin/env bash
# Gate 38 — ACME continuous AFDD qualification (primary live AFDD SoT).
# Synthetic-59 flood remains gate 19; this gate proves ACME lookback-sized cycles.
#
# Window policy — plan_continuous_cycle (crates/fdd_store/src/afdd_scheduler.rs):
#   end   = latest persisted telemetry watermark
#   start = end − lookback
# Cycles use a lookback-sized window only, tied to the interval
# (daily cadence → 24h / 1 day). They do not scan the entire historian.
# After downtime the next cycle is still one lookback-sized window
# (catch_up). Explicit history replay is plan_backfill_chunks, separate
# from the timer.
#
# Cadence: interval mode uses OPENFDD_AFDD_INTERVAL_MINUTES=1440
# (last_completed_at + interval). Wall-clock mode
# (OPENFDD_AFDD_SCHEDULE=wall_clock, HH:MM + IANA timezone) pins a local
# day. The lab recipe is 05:00 America/Chicago before the 06:00 digest.
# This gate still expects the live interval pin (1440 / 24h). It records
# schedule_kind and proves the configured kind: wall-clock next_due local
# HH:MM, or interval next_due = last_completed + interval. It does not
# require 05:00 until OPENFDD_ACME_AFDD_EXPECT_SCHEDULE=wall_clock.
# Outside-window slices come from GET /api/afdd/scheduler/result-slices
# (rows_sha256). Slices that are not fully inside the cycle window must keep
# that hash. update_all on the scheduler config must be rejected and must
# not change the saved config. Central stay-up is started_at + uptime across
# the cycle (STRESS NOTE #1). Host RSS is recorded; it is not the replica cap.
#
# Live lab env (Railway, not a product default): OPENFDD_AFDD_MODE=continuous,
# INTERVAL_MINUTES=1440, LOOKBACK_VALUE=24, LOOKBACK_UNIT=hours,
# BUILDING_ID=ACME. RAM watch: STRESS NOTE #1 (Pro central 24 GB/replica).
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
EXPECT_SCHEDULE="${OPENFDD_ACME_AFDD_EXPECT_SCHEDULE:-}"

python3 - <<'PY' "$CENTRAL_BASE" "$OUT" "$SUMMARY" "$BUILDING" "$MAX_WALL" "$EXPECT_INTERVAL" "$EXPECT_LOOKBACK_HOURS" "$EXPECT_SCHEDULE"
import json, os, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

base, out, summary, building, max_wall, expect_interval, expect_lb_h, expect_schedule = sys.argv[1:9]
expect_schedule = expect_schedule.strip().lower()
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
schedule_kind = (cfg.get("schedule_kind") or status.get("schedule_kind") or "interval")
result_write = status.get("result_write")
report["checks"]["config"] = {
    "ok": cfg_ok,
    "mode": mode,
    "interval_minutes": interval,
    "lookback_value": lb_value,
    "lookback_unit": lb_unit,
    "lookback_hours": lookback_hours,
    "timer_scope": timer_scope,
    "schedule_kind": schedule_kind,
    "wall_clock_hhmm": cfg.get("wall_clock_hhmm"),
    "wall_clock_timezone": cfg.get("wall_clock_timezone"),
    "next_due_at_utc": status.get("next_due_at_utc"),
    "next_due_local": status.get("next_due_local"),
    "result_write": result_write,
}
# Soft-open: older hubs omit result_write. A present value must be the
# lookback upsert, never an update-all scope.
if result_write not in (None, "", "lookback_window"):
    report["error"] = f"scheduler result_write={result_write!r} is not lookback_window"
    open(out, "w").write(json.dumps(report, indent=2))
    open(summary, "w").write(f"# Gate 38 FAIL\n\n{report['error']}\n")
    raise SystemExit(1)
if not cfg_ok:
    report["error"] = (
        f"config truth failed: want continuous/{expect_interval}min/"
        f"{expect_lb_h}h scope={building}; got mode={mode} interval={interval} "
        f"lookback={lb_value}{lb_unit} scope={timer_scope}"
    )
    open(out, "w").write(json.dumps(report, indent=2))
    open(summary, "w").write(f"# Gate 38 FAIL\n\n{report['error']}\n")
    raise SystemExit(1)

def gate_fail(message, check=None, payload=None):
    report["error"] = message
    if check is not None:
        report["checks"][check] = payload if payload is not None else {"ok": False}
    open(out, "w").write(json.dumps(report, indent=2))
    open(summary, "w").write(f"# Gate 38 FAIL\n\n{message}\n")
    raise SystemExit(1)

def config_view(body):
    cfg_body = body.get("config") or {}
    return {
        "mode": cfg_body.get("mode"),
        "interval_minutes": cfg_body.get("interval_minutes"),
        "lookback_value": cfg_body.get("lookback_value"),
        "lookback_unit": cfg_body.get("lookback_unit"),
        "schedule_kind": cfg_body.get("schedule_kind") or body.get("schedule_kind"),
        "wall_clock_hhmm": cfg_body.get("wall_clock_hhmm"),
        "wall_clock_timezone": cfg_body.get("wall_clock_timezone"),
    }

def local_hhmm(raw):
    if not isinstance(raw, str) or "T" not in raw:
        return None
    return raw.split("T", 1)[1][:5]

# A2. Central identity before the cycle (stay-up / STRESS NOTE #1).
try:
    _, health_before = http("GET", "/api/health", token=token, timeout=30)
except Exception as e:
    gate_fail(f"health before AFDD failed: {e}", "central_stay_up")
started_before = health_before.get("started_at")
uptime_before = health_before.get("uptime_secs")
if health_before.get("ok") is False:
    gate_fail("health not ok before AFDD", "central_stay_up", {"ok": False, "before": health_before})

def memory_sample():
    try:
        st, body = http("GET", "/api/host/stats", token=token, timeout=30)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    mem = body.get("memory") if isinstance(body.get("memory"), dict) else {}
    return {
        "http": st,
        "memory_used_bytes": mem.get("used_bytes"),
        "memory_percent_used": mem.get("percent_used"),
        "memory_total_bytes": mem.get("total_bytes"),
        "memory_source": mem.get("source"),
    }

mem_before = memory_sample()

# A3. Result-slice fingerprints before the cycle.
slice_path = "/api/afdd/scheduler/result-slices?building_id=" + urllib.parse.quote(building)
try:
    _, slices_before = http("GET", slice_path, token=token)
except urllib.error.HTTPError as e:
    gate_fail(
        f"result-slices HTTP {e.code} (lookback upsert proof needs this route)",
        "outside_window",
        {"ok": False, "http": e.code},
    )
except Exception as e:
    gate_fail(f"result-slices failed: {e}", "outside_window")
if slices_before.get("ok") is False:
    gate_fail(
        f"result-slices error: {slices_before.get('error')}",
        "outside_window",
        {"ok": False, "body": slices_before},
    )

# B. Live cycle on the timer scope
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

result_scope = cycle.get("result_scope")
if result_scope not in (None, "", "lookback_window"):
    report["error"] = f"cycle result_scope={result_scope!r} is not lookback_window"
    report["checks"]["run_now"] = {"ok": False, "result_scope": result_scope}
    open(out, "w").write(json.dumps(report, indent=2))
    open(summary, "w").write(f"# Gate 38 FAIL\n\n{report['error']}\n")
    raise SystemExit(1)

report["checks"]["run_now"] = {
    "ok": ok and scope.upper() == building.upper() and elapsed <= max_wall,
    "http": st,
    "result_scope": result_scope,
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
    gate_fail(f"efficiency check failed window_hours={window_hours} executed={executed}")

def slice_entries(body):
    entries = []
    for rule in body.get("rules") or []:
        rid = rule.get("rule_id")
        for window in rule.get("windows") or []:
            entries.append((rid, window))
    return entries

def fully_inside(window, win_start, win_end):
    if window.get("preserved_unscoped") or window.get("legacy_unscoped"):
        return False
    ws = parse_dt(window.get("start_utc"))
    we = parse_dt(window.get("end_utc"))
    if ws is None or we is None or win_start is None or win_end is None:
        return False
    return ws >= win_start and we <= win_end

def slice_key(rid, window):
    return (
        rid,
        window.get("start_utc"),
        window.get("end_utc"),
        bool(window.get("preserved_unscoped")),
        bool(window.get("legacy_unscoped")),
        window.get("rows_sha256"),
    )

# F. Outside-window slices stay hash-identical. No prior outside slice is a
# recorded observation; the fdd_store fixture is the non-vacuous proof.
try:
    _, slices_after = http("GET", slice_path, token=token)
except Exception as e:
    gate_fail(f"result-slices after cycle failed: {e}", "outside_window")
outside_before = [
    slice_key(rid, window)
    for rid, window in slice_entries(slices_before)
    if not fully_inside(window, start, end)
]
after_keys = {slice_key(rid, window) for rid, window in slice_entries(slices_after)}
missing = [key for key in outside_before if key not in after_keys]
bad_scope = [
    rule.get("rule_id")
    for rule in slices_after.get("rules") or []
    if rule.get("result_scope") not in (None, "", "lookback_window")
]
outside_ok = not missing and not bad_scope
report["checks"]["outside_window"] = {
    "ok": outside_ok,
    "prior_outside_slices": len(outside_before),
    "missing": [
        {"rule_id": key[0], "start_utc": key[1], "end_utc": key[2], "rows_sha256": key[5]}
        for key in missing[:20]
    ],
    "bad_result_scope": bad_scope[:20],
}
if not outside_ok:
    gate_fail(
        f"lookback upsert rewrote slices outside the cycle window "
        f"(missing={len(missing)} bad_scope={bad_scope[:5]})",
        "outside_window",
        report["checks"]["outside_window"],
    )

# G. Scheduler config rejects update-all and does not persist it.
saved = config_view(status)
try:
    _, rejected = http(
        "POST",
        "/api/afdd/scheduler/config",
        token=token,
        body={"update_all": True},
    )
except Exception as e:
    gate_fail(f"update_all probe failed: {e}", "update_all_rejected")
_, status_after_probe = http("GET", "/api/afdd/scheduler/status", token=token)
still = config_view(status_after_probe)
err_text = str(rejected.get("error") or "").lower()
rejected_ok = (
    rejected.get("ok") is False
    and still == saved
    and any(needle in err_text for needle in ("update all", "retained", "unbounded"))
)
report["checks"]["update_all_rejected"] = {
    "ok": rejected_ok,
    "response_ok": rejected.get("ok"),
    "error": rejected.get("error"),
    "config_unchanged": still == saved,
}
if not rejected_ok:
    gate_fail(
        "scheduler accepted update_all or changed config while rejecting it",
        "update_all_rejected",
        report["checks"]["update_all_rejected"],
    )

# H. Schedule semantics for the configured kind.
schedule_errors = []
if expect_schedule and schedule_kind != expect_schedule:
    schedule_errors.append(
        f"schedule_kind {schedule_kind!r} != expected {expect_schedule!r}"
    )
if schedule_kind == "wall_clock":
    hhmm = cfg.get("wall_clock_hhmm") or ""
    tz_name = cfg.get("wall_clock_timezone") or ""
    local = status.get("next_due_local")
    if not hhmm or not tz_name:
        schedule_errors.append("wall_clock is missing HH:MM or IANA timezone")
    elif local_hhmm(local) != hhmm:
        schedule_errors.append(f"next_due_local {local!r} is not {hhmm} {tz_name}")
elif schedule_kind in ("interval", "", None):
    checkpoint = status.get("checkpoint") if isinstance(status.get("checkpoint"), dict) else {}
    last = parse_dt((checkpoint or {}).get("last_completed_at_utc"))
    due = parse_dt(status.get("next_due_at_utc"))
    if last and due:
        delta_min = (due - last).total_seconds() / 60.0
        if abs(delta_min - interval) > 2:
            schedule_errors.append(
                f"next_due delta {delta_min:.1f} min != interval {interval}"
            )
else:
    schedule_errors.append(f"unknown schedule_kind {schedule_kind!r}")
cadence_hours = 24.0 if schedule_kind == "wall_clock" else interval / 60.0
matches = status.get("lookback_matches_cadence")
if matches is False and abs(lookback_hours - cadence_hours) < 0.01:
    schedule_errors.append("lookback_matches_cadence is false for a cadence-sized lookback")
if matches is True and abs(lookback_hours - cadence_hours) > 0.01:
    schedule_errors.append("lookback_matches_cadence is true but lookback differs from cadence")
report["checks"]["schedule_semantics"] = {
    "ok": not schedule_errors,
    "schedule_kind": schedule_kind,
    "next_due_at_utc": status.get("next_due_at_utc"),
    "next_due_local": status.get("next_due_local"),
    "lookback_matches_cadence": matches,
    "errors": schedule_errors,
}
if schedule_errors:
    gate_fail("; ".join(schedule_errors), "schedule_semantics", report["checks"]["schedule_semantics"])

# I. Central stayed up across the cycle (restart / OOM shows up as a new process).
try:
    _, health_after = http("GET", "/api/health", token=token, timeout=30)
except Exception as e:
    gate_fail(f"health after AFDD failed: {e}", "central_stay_up")
mem_after = memory_sample()
started_after = health_after.get("started_at")
uptime_after = health_after.get("uptime_secs")
stay_errors = []
if health_after.get("ok") is False:
    stay_errors.append("health not ok after AFDD")
if started_before and started_after != started_before:
    stay_errors.append("central restarted during AFDD (started_at changed)")
if isinstance(uptime_before, (int, float)) and isinstance(uptime_after, (int, float)):
    if uptime_after + 1 < uptime_before:
        stay_errors.append("uptime reset during AFDD")
report["checks"]["central_stay_up"] = {
    "ok": not stay_errors,
    "started_at_before": started_before,
    "started_at_after": started_after,
    "uptime_secs_before": uptime_before,
    "uptime_secs_after": uptime_after,
    "memory_before": mem_before,
    "memory_after": mem_after,
    "errors": stay_errors,
    "note": "RSS is not the Railway replica cgroup cap (STRESS NOTE #1, Pro 24 GB)",
}
if stay_errors:
    gate_fail("; ".join(stay_errors), "central_stay_up", report["checks"]["central_stay_up"])

report["ok"] = True
report["window_hours"] = window_hours
report["elapsed_secs"] = round(elapsed, 3)

open(out, "w").write(json.dumps(report, indent=2))
open(summary, "w").write(
    f"""# Gate 38 PASS — ACME continuous AFDD qual

- building: `{building}`
- config: continuous / {interval} min / {lookback_hours}h lookback / timer_scope={timer_scope}
- schedule_kind: `{schedule_kind}` lookback_matches_cadence={matches}
- cycle run_id: `{run_id}`
- window_hours: {window_hours}
- elapsed_secs: {elapsed:.1f}
- rules_succeeded/failed/skipped: {succ}/{fail}/{skip} (executed={executed})
- outside slices preserved: {len(outside_before)}
- update_all rejected; central started_at unchanged
"""
)
print(summary, "PASS", flush=True)
raise SystemExit(0)
PY
