#!/usr/bin/env bash
# Gate 10–12 Streamlit UI soak checks (replaces React LabShell / /srv/assets asserts — #564).
#
# Usage (against a running stack):
#   CENTRAL=http://127.0.0.1:8080 UI=http://127.0.0.1:3000 ./scripts/release/smoke_streamlit_ui_gates.sh
# Optional JWT:
#   OPENFDD_ADMIN_PASSWORD=...  or  TOKEN=eyJ...
set -euo pipefail

CENTRAL="${CENTRAL:-http://127.0.0.1:8080}"
UI="${UI:-http://127.0.0.1:3000}"
FAIL=0

pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; FAIL=1; }

echo "== Streamlit UI gates 10–12 (CENTRAL=$CENTRAL UI=$UI) =="

# --- Gate 10: Streamlit chrome (not React LabShell) ---
ui_html="$(curl -fsS "$UI/" | head -c 8000 || true)"
if echo "$ui_html" | grep -qi '<title>Streamlit</title>'; then
  pass "gate10 UI is Streamlit shell"
else
  fail "gate10 expected <title>Streamlit</title> at $UI/"
fi
if echo "$ui_html" | grep -qE '/srv/assets/index-.*\.js'; then
  fail "gate10 found React /srv/assets/index-*.js — product UI should be Streamlit"
else
  pass "gate10 no React /srv/assets bundle"
fi

# Health endpoint Streamlit exposes
if curl -fsS -o /dev/null -w '%{http_code}' "$UI/_stcore/health" | grep -q 200; then
  pass "gate10 Streamlit _stcore/health"
else
  fail "gate10 Streamlit _stcore/health not 200"
fi

# --- Auth header helper ---
AUTH=()
if [[ -n "${TOKEN:-}" ]]; then
  AUTH=(-H "Authorization: Bearer $TOKEN")
elif [[ -n "${OPENFDD_ADMIN_PASSWORD:-}" ]]; then
  TOKEN="$(curl -fsS -X POST "$CENTRAL/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${OPENFDD_UI_USERNAME:-admin}\",\"password\":\"$OPENFDD_ADMIN_PASSWORD\"}" \
    | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("access_token") or d.get("token") or "")')"
  if [[ -n "$TOKEN" && "$TOKEN" != "open" ]]; then
    AUTH=(-H "Authorization: Bearer $TOKEN")
  fi
fi

# --- Gate 11: dashboard/central APIs still useful to Streamlit (no React shell required) ---
for path in /api/health /api/capabilities /api/fdd/rules /api/fdd/cache/status; do
  code="$(curl -sS -o /tmp/gate11.json -w '%{http_code}' "${AUTH[@]}" "$CENTRAL$path" || echo 000)"
  if [[ "$code" == "200" ]]; then
    pass "gate11 $path → 200"
  else
    fail "gate11 $path → HTTP $code"
  fi
done
# SQL FDD run shape (may 401 without token on JWT stacks — still assert JSON contract when ok)
run_code="$(curl -sS -o /tmp/gate11_run.json -w '%{http_code}' "${AUTH[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"mode":"registry","rule_ids":["FC1"]}' \
  "$CENTRAL/api/fdd/run" || echo 000)"
if [[ "$run_code" == "200" ]]; then
  python3 - <<'PY' || fail "gate11 fdd/run JSON shape"
import json
d=json.load(open("/tmp/gate11_run.json"))
assert d.get("ok") is True, d
assert "DataFusion" in str(d.get("engine","")) or d.get("mode")=="registry", d
print("ok")
PY
  pass "gate11 POST /api/fdd/run DataFusion"
elif [[ "$run_code" == "401" ]]; then
  pass "gate11 POST /api/fdd/run requires JWT (expected without TOKEN/ADMIN_PASSWORD)"
else
  fail "gate11 POST /api/fdd/run → HTTP $run_code"
fi

# --- Gate 12: parity honesty (docs claim) ---
if curl -fsS "${AUTH[@]}" -o /tmp/gate12_rules.json "$CENTRAL/api/fdd/rules" 2>/dev/null \
  || curl -fsS -o /tmp/gate12_rules.json "$CENTRAL/api/fdd/rules"; then
  python3 - <<'PY' || fail "gate12 rules catalog"
import json
d=json.load(open("/tmp/gate12_rules.json"))
rules=d.get("rules") or []
assert len(rules) >= 50, len(rules)
# Do not require "full pandas parity" wording anywhere in this response.
blob=json.dumps(d).lower()
assert "54 full parity" not in blob
print(f"rules={len(rules)}")
PY
  pass "gate12 SQL registry present; no false full-parity claim in API blob"
else
  fail "gate12 could not fetch /api/fdd/rules"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "PASS: Streamlit gates 10–12"
  exit 0
fi
echo "FAIL: Streamlit gates 10–12"
exit 1
