#!/usr/bin/env bash
# BUILDING_100 Railway vs local WattLab-style parity spot-check.
# Captures FDD, series, runtime, and analytics APIs on both hubs; emits summary.json.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCAL_BASE="${LOCAL_BASE:-http://127.0.0.1:8080}"
RAILWAY_BASE="${RAILWAY_BASE:-https://openfdd-web-production-af99.up.railway.app}"
BUILDING_ID="${BUILDING_ID:-BUILDING_100}"
EQUIPMENT_ID="${EQUIPMENT_ID:-AHU_1}"
RULE_ID="${RULE_ID:-FC1}"
FAULT_TOL="${FAULT_TOL:-0.05}"
RUNTIME_TOL="${RUNTIME_TOL:-0.01}"

UTC="$(date -u +%Y%m%dT%H%M%SZ)"
ART="${ARTIFACT_DIR:-$ROOT/reports/railway-b100-parity_${UTC}}"
mkdir -p "$ART"

if [[ -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  set -a && source "$ROOT/.env" && set +a
fi

login() {
  local base="$1" user="$2" pass="$3"
  curl -fsS --max-time 30 -X POST "$base/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u "$user" --arg p "$pass" '{username:$u,password:$p}')" \
    | jq -r '.token // .access_token // empty'
}

capture_side() {
  local label="$1" base="$2" token="$3"
  local dir="$ART/$label"
  mkdir -p "$dir"

  curl -fsS --max-time 20 "$base/api/health" >"$dir/health.json" || echo '{}' >"$dir/health.json"

  curl -fsS --max-time 300 -X POST "$base/api/fdd/run" \
    -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg b "$BUILDING_ID" '{mode:"registry",building_id:$b,rule_ids:["FC1"],params:{}}')" \
    >"$dir/fdd_run.json" 2>"$dir/fdd_run.err" || echo '{"ok":false}' >"$dir/fdd_run.json"

  curl -fsS --max-time 120 "$base/api/fdd/results?building_id=$BUILDING_ID" \
    -H "Authorization: Bearer $token" >"$dir/fdd_results.json" 2>/dev/null \
    || echo '{"ok":false}' >"$dir/fdd_results.json"

  curl -fsS --max-time 120 \
    "$base/api/fdd/series?building_id=$BUILDING_ID&equipment_id=$EQUIPMENT_ID&rule_id=$RULE_ID" \
    -H "Authorization: Bearer $token" >"$dir/fdd_series.json" 2>/dev/null \
    || echo '{"ok":false}' >"$dir/fdd_series.json"

  curl -fsS --max-time 120 -X POST "$base/api/analytics/runtime" \
    -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg b "$BUILDING_ID" '{building_id:$b}')" \
    >"$dir/runtime.json" 2>/dev/null || echo '{}' >"$dir/runtime.json"

  curl -fsS --max-time 120 -X POST "$base/api/analytics/ahu-pressure-health" \
    -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg b "$BUILDING_ID" '{building_id:$b}')" \
    >"$dir/ahu_pressure_health.json" 2>/dev/null || echo '{}' >"$dir/ahu_pressure_health.json"

  curl -fsS --max-time 180 -X POST "$base/api/analytics/mechanical-cooling" \
    -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg b "$BUILDING_ID" '{building_id:$b}')" \
    >"$dir/mechanical_cooling.json" 2>/dev/null || echo '{}' >"$dir/mechanical_cooling.json"
}

echo "== BUILDING_100 parity capture =="
echo "artifact=$ART"

LOCAL_PASS="${OPENFDD_ADMIN_PASSWORD:-}"
if [[ -z "$LOCAL_PASS" ]]; then
  echo "ERROR: OPENFDD_ADMIN_PASSWORD required in env or $ROOT/.env" >&2
  exit 2
fi
LOCAL_TOKEN="$(login "$LOCAL_BASE" admin "$LOCAL_PASS")"
[[ -n "$LOCAL_TOKEN" ]] || { echo "ERROR: local login failed" >&2; exit 2; }
capture_side local "$LOCAL_BASE" "$LOCAL_TOKEN"

RAILWAY_PASS="${RAILWAY_ADMIN_PASSWORD:-}"
if [[ -z "$RAILWAY_PASS" ]] && command -v railway >/dev/null 2>&1; then
  RAILWAY_PASS="$(railway variables --service openfdd-central-cQ-F --json 2>/dev/null \
    | jq -r '.OPENFDD_ADMIN_PASSWORD // empty' || true)"
fi
if [[ -z "$RAILWAY_PASS" ]]; then
  echo "WARN: RAILWAY_ADMIN_PASSWORD unset — skipping railway capture" >&2
else
  RAILWAY_TOKEN="$(login "$RAILWAY_BASE" admin "$RAILWAY_PASS")"
  [[ -n "$RAILWAY_TOKEN" ]] || { echo "ERROR: railway login failed" >&2; exit 2; }
  capture_side railway "$RAILWAY_BASE" "$RAILWAY_TOKEN"
fi

python3 - "$ART" "$BUILDING_ID" "$EQUIPMENT_ID" "$RULE_ID" "$FAULT_TOL" "$RUNTIME_TOL" <<'PY'
import json
import math
import sys
from pathlib import Path

art, building, equip, rule, fault_tol, runtime_tol = sys.argv[1:7]
fault_tol = float(fault_tol)
runtime_tol = float(runtime_tol)
root = Path(art)


def load(side, name):
    p = root / side / name
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def fc1_fault_hours(data):
    for key in ("results", "rows"):
        for r in data.get(key) or []:
            if str(r.get("rule_id")) == "FC1" and str(r.get("equipment_id")) == equip:
                try:
                    return float(r.get("fault_hours"))
                except (TypeError, ValueError):
                    return None
    run = load("local" if data is load("local", "fdd_run.json") else "railway", "fdd_run.json")
    for r in run.get("results") or []:
        if str(r.get("rule_id")) == "FC1" and str(r.get("equipment_id")) == equip:
            try:
                return float(r.get("fault_hours"))
            except (TypeError, ValueError):
                pass
    return None


def ahu_runtime(data):
    env = data.get("analytics") or data.get("data") or data
    rows = env.get("equipment") or env.get("rows") or []
    for r in rows:
        if str(r.get("equipment_id")) == equip:
            for k in ("run_hours", "hours"):
                if r.get(k) is not None:
                    try:
                        return float(r[k])
                    except (TypeError, ValueError):
                        pass
    return None


def duct_low(data):
    env = data.get("analytics") or data.get("data") or data
    rows = env.get("rows") or []
    for r in rows:
        if str(r.get("equipment_id")) == equip:
            flags = r.get("flags") or r
            if "duct_low" in flags:
                return bool(flags.get("duct_low"))
    return None


def extract(side):
    run = load(side, "fdd_run.json")
    results = load(side, "fdd_results.json")
    series = load(side, "fdd_series.json")
    runtime = load(side, "runtime.json")
    fh = None
    for src in (run, results):
        for r in src.get("results") or src.get("rows") or []:
            if str(r.get("rule_id")) == rule and str(r.get("equipment_id")) == equip:
                try:
                    fh = float(r.get("fault_hours"))
                    break
                except (TypeError, ValueError):
                    pass
        if fh is not None:
            break
    return {
        "version": (load(side, "health.json").get("version")),
        "fc1_fault_hours": fh,
        "poll_seconds": run.get("poll_seconds"),
        "has_confirmed_fault": series.get("has_confirmed_fault"),
        "series_ok": series.get("ok"),
        "run_hours": ahu_runtime(runtime),
        "duct_low": duct_low(load(side, "ahu_pressure_health.json")),
    }


local = extract("local")
railway = extract("railway") if (root / "railway").is_dir() else {}

checks = []
def add(name, ok, detail):
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


if railway:
    lf, rf = local.get("fc1_fault_hours"), railway.get("fc1_fault_hours")
    if lf is not None and rf is not None:
        add("fc1_fault_hours_parity", abs(lf - rf) <= fault_tol, f"local={lf} railway={rf} tol={fault_tol}")
    else:
        add("fc1_fault_hours_parity", False, f"missing local={lf} railway={rf}")

    lr, rr = local.get("run_hours"), railway.get("run_hours")
    if lr is not None and rr is not None:
        add("runtime_parity", abs(lr - rr) <= runtime_tol, f"local={lr} railway={rr} tol={runtime_tol}")
    else:
        add("runtime_parity", False, f"missing local={lr} railway={rr}")

    add(
        "series_confirmed_fault",
        local.get("has_confirmed_fault") is True and railway.get("has_confirmed_fault") is True,
        f"local={local.get('has_confirmed_fault')} railway={railway.get('has_confirmed_fault')}",
    )
    lp, rp = local.get("poll_seconds"), railway.get("poll_seconds")
    if lp is not None and rp is not None:
        add("poll_seconds_parity", lp == rp, f"local={lp} railway={rp}")
else:
    add("railway_capture", False, "railway side not captured")

summary = {
    "building_id": building,
    "equipment_id": equip,
    "rule_id": rule,
    "local": local,
    "railway": railway,
    "checks": checks,
    "pass": all(c["ok"] for c in checks) if checks else False,
}
(root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
sys.exit(0 if summary["pass"] else 1)
PY

echo "wrote $ART/summary.json"
