#!/usr/bin/env bash
# OFDD-CADDY soak IT: GET / and GET /api/health via Caddy (default http://127.0.0.1).
set -euo pipefail
BASE="${OPENFDD_CADDY_BASE:-http://127.0.0.1}"
fail=0

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/openfdd-caddy.XXXXXX")"
trap 'rm -rf -- "$tmp_dir"' EXIT
root_body="$tmp_dir/root.body"
health_body="$tmp_dir/health.json"

code_root="$(curl -sS -o "$root_body" -w '%{http_code}' --max-time 15 "$BASE/" || echo 000)"
if [[ "$code_root" != "200" ]]; then
  echo "FAIL GET / → HTTP $code_root (expected 200)" >&2
  fail=1
else
  echo "OK GET / → 200"
fi

code_health="$(curl -sS -o "$health_body" -w '%{http_code}' --max-time 15 "$BASE/api/health" || echo 000)"
if [[ "$code_health" != "200" ]]; then
  echo "FAIL GET /api/health → HTTP $code_health (expected 200)" >&2
  fail=1
else
  echo "OK GET /api/health → 200"
  if command -v python3 >/dev/null 2>&1; then
    HEALTH_BODY="$health_body" python3 - <<'PY'
import json
import os
from pathlib import Path
doc = json.loads(Path(os.environ["HEALTH_BODY"]).read_text())
assert doc.get("ok") is True or "version" in doc or "status" in doc, doc
print("OK health JSON keys:", sorted(doc)[:12])
PY
  fi
fi

# /login must not be a blank SPA — follow redirects to /auth.
login_hdr="$tmp_dir/login.hdr"
login_body="$tmp_dir/login.body"
code_login="$(curl -sS -D "$login_hdr" -o "$login_body" -w '%{http_code}' --max-time 15 "$BASE/login" || echo 000)"
if [[ "$code_login" == "301" || "$code_login" == "302" ]]; then
  loc="$(awk 'BEGIN{IGNORECASE=1} /^location:/ {print $2}' "$login_hdr" | tr -d '\r' | tail -1)"
  echo "OK GET /login → $code_login Location=$loc"
  if [[ "$loc" != *"/auth"* ]]; then
    echo "FAIL /login redirect target not /auth: $loc" >&2
    fail=1
  fi
elif [[ "$code_login" == "200" ]]; then
  # SPA Navigate path: HTML ok but must not be an empty product tree when followed in browser.
  # Curl-level: ensure we did not get a soft 404; Playwright gate covers DOM.
  echo "OK GET /login → 200 (SPA; Playwright asserts /auth markers)"
else
  echo "FAIL GET /login → HTTP $code_login (expected 302→/auth or 200)" >&2
  fail=1
fi

exit "$fail"
