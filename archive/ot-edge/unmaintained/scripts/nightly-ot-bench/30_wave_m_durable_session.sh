#!/usr/bin/env bash
# Wave M durable-results gates 1-3 (session / job switch / stale 401).
# Primary target: tip compose or disposable candidate (RAILWAY_ONLY optional).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
OUT="$ART/30_wave_m_durable_session.json"

python3 - <<'PY' "$CENTRAL_BASE" "$OUT"
import json, os, sys, urllib.request, urllib.error
base = sys.argv[1].rstrip("/")
out = sys.argv[2]
admin_user = os.environ.get("OPENFDD_ADMIN_USER", "admin")
admin_pass = os.environ.get("OPENFDD_ADMIN_PASSWORD", "")

def http(method, path, token=None, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode() if e.fp else ""
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {"raw": raw}
        return e.code, payload

report = {
    "ok": False,
    "gates": {},
    "hub": base,
}
st, health = http("GET", "/api/health")
report["health"] = {"status": st, "body": {k: health.get(k) for k in ("ok", "version", "multi_tenant")}}
if st != 200 or not health.get("ok"):
    report["error"] = "health failed"
    open(out, "w").write(json.dumps(report, indent=2))
    raise SystemExit(1)

token = None
if admin_pass:
    st, login = http("POST", "/api/auth/login", body={"username": admin_user, "password": admin_pass})
    token = login.get("access_token") or login.get("token")
    report["gates"]["login"] = {"status": st, "ok": bool(token)}
else:
    report["gates"]["login"] = {"status": "SKIPPED", "reason": "no OPENFDD_ADMIN_PASSWORD"}

# Gate 1: results endpoint reachable without forcing recompute (read path)
st, results = http("GET", "/api/fdd/results", token=token)
report["gates"]["gate1_read_results"] = {
    "status": st,
    "ok": st in (200, 401, 404),  # 401 when auth required and no password in env
    "note": "read path must not 5xx; empty/auth is honest",
}

# Gate 2: tenant/job listing isolation surface present
st, tenants = http("GET", "/api/tenants", token=token)
report["gates"]["gate2_tenants"] = {
    "status": st,
    "ok": st == 200,
    "multi_tenant": tenants.get("multi_tenant"),
}

# Gate 3: stale session contract - /api/auth/me with garbage token must 401 without killing hub
st, me = http("GET", "/api/auth/me", token="stale.invalid.token")
report["gates"]["gate3_stale_token"] = {
    "status": st,
    "ok": st in (401, 200),  # 200 only when auth disabled
    "note": "browser session-gen handled in UI; API must not 5xx",
}

report["ok"] = all(g.get("ok") for g in report["gates"].values() if isinstance(g, dict) and "ok" in g)
open(out, "w").write(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
raise SystemExit(0 if report["ok"] else 1)
PY
