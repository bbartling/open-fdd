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

exit "$fail"
