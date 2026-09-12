#!/usr/bin/env bash
# Wave M gate 12 - AFDD flood (budgeted, isolated-candidate default).
# Enhance don't butcher: fixed fixture expectations; budgets FAIL not silent trim.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
OUT="$ART/2N_wave_m_afdd_flood.json"
SUMMARY="$ART/2N_wave_m_afdd_flood.md"

# Budgets (pre-agreed; exceed = FAIL)
MAX_WALL_SECS="${OPENFDD_AFDD_FLOOD_MAX_WALL_SECS:-900}"
MAX_RULES="${OPENFDD_AFDD_FLOOD_MAX_RULES:-80}"
FIXTURE="${OPENFDD_AFDD_FLOOD_FIXTURE:-Synthetic-59}"
ALLOW_LIVE="${OPENFDD_AFDD_FLOOD_ALLOW_LIVE:-0}"

if [[ "${RAILWAY_ONLY:-0}" == "1" && "$ALLOW_LIVE" != "1" ]]; then
  cat >"$OUT" <<EOF
{"ok":false,"status":"BLOCKED","reason":"AFDD flood defaults to isolated candidate; set OPENFDD_AFDD_FLOOD_ALLOW_LIVE=1 for authorized live window"}
EOF
  echo "BLOCKED: refuse unbounded live-hub AFDD flood (set OPENFDD_AFDD_FLOOD_ALLOW_LIVE=1 to authorize)" | tee "$SUMMARY"
  exit 2
fi

python3 - <<'PY' "$CENTRAL_BASE" "$OUT" "$SUMMARY" "$MAX_WALL_SECS" "$MAX_RULES" "$FIXTURE"
import json, os, sys, time, urllib.request, urllib.error
base, out, summary, max_wall, max_rules, fixture = sys.argv[1:7]
max_wall = int(max_wall); max_rules = int(max_rules)
admin_user = os.environ.get("OPENFDD_ADMIN_USER", "admin")
admin_pass = os.environ.get("OPENFDD_ADMIN_PASSWORD", "")
building = os.environ.get("OPENFDD_AFDD_FLOOD_BUILDING", "SYNTHETIC_59")

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

report = {
    "ok": False,
    "fixture": fixture,
    "building_id": building,
    "budgets": {"max_wall_secs": max_wall, "max_rules": max_rules},
    "hub": base,
}
token = None
if admin_pass:
    _, login = http("POST", "/api/auth/login", body={"username": admin_user, "password": admin_pass})
    token = login.get("access_token") or login.get("token")

t0 = time.time()
# Prefer durable AFDD run-now (scheduler path) over browser mash.
# Include fixture identity for evidence; only fall back on HTTP 404 (route missing).
payload = {"building_id": building, "fixture": fixture}
try:
    st, body = http("POST", "/api/afdd/scheduler/run-now", token=token, body=payload, timeout=max_wall)
except urllib.error.HTTPError as e:
    if e.code != 404:
        report["error"] = f"flood scheduler invoke failed HTTP {e.code}: {e.reason}"
        open(out, "w").write(json.dumps(report, indent=2))
        open(summary, "w").write(f"# AFDD flood FAIL\n\n{report['error']}\n")
        raise SystemExit(1)
    try:
        st, body = http(
            "POST",
            "/api/fdd/run",
            token=token,
            body={"mode": "registry", "building_id": building, "fixture": fixture},
            timeout=max_wall,
        )
    except Exception as e2:
        report["error"] = f"flood invoke failed: scheduler 404; fallback: {e2}"
        open(out, "w").write(json.dumps(report, indent=2))
        open(summary, "w").write(f"# AFDD flood FAIL\n\n{report['error']}\n")
        raise SystemExit(1)
except Exception as e:
    report["error"] = f"flood scheduler invoke failed: {e}"
    open(out, "w").write(json.dumps(report, indent=2))
    open(summary, "w").write(f"# AFDD flood FAIL\n\n{report['error']}\n")
    raise SystemExit(1)

elapsed = time.time() - t0
rules_run = int(body.get("rules_run") or body.get("rules_succeeded") or 0)
rules_failed = int(body.get("rules_failed") or 0)
report.update({
    "http_status": st,
    "elapsed_secs": round(elapsed, 3),
    "run": {
        "ok": bool(body.get("ok", st == 200)),
        "run_id": body.get("run_id"),
        "status": body.get("status"),
        "rules_run": body.get("rules_run"),
        "rules_succeeded": body.get("rules_succeeded"),
        "rules_failed": body.get("rules_failed"),
        "rules_skipped": body.get("rules_skipped"),
        "total_ms": body.get("total_ms"),
    },
})

reasons = []
if elapsed > max_wall:
    reasons.append(f"wall clock {elapsed:.1f}s > budget {max_wall}s")
if rules_run and rules_run > max_rules:
    reasons.append(f"rules_run {rules_run} > budget {max_rules}")
if rules_failed:
    reasons.append(f"rules_failed={rules_failed} (do not weaken fixtures)")
if not body.get("ok", st == 200):
    reasons.append("invoke returned ok=false")

report["ok"] = not reasons
report["fail_reasons"] = reasons
open(out, "w").write(json.dumps(report, indent=2) + "\n")
lines = [
    f"# AFDD flood - {'PASS' if report['ok'] else 'FAIL'}",
    "",
    f"- Fixture: `{fixture}` building `{building}`",
    f"- Elapsed: {elapsed:.1f}s (budget {max_wall}s)",
    f"- Rules failed: {rules_failed}",
    f"- Reasons: {reasons or ['none']}",
    "",
]
open(summary, "w").write("\n".join(lines))
print(json.dumps(report, indent=2))
raise SystemExit(0 if report["ok"] else 1)
PY
