#!/usr/bin/env bash
# OFDD-CADDY soak IT: GET / and GET /api/health via Caddy (default http://127.0.0.1).
set -euo pipefail
BASE="${OPENFDD_CADDY_BASE:-http://127.0.0.1}"
fail=0

code_root="$(curl -sS -o /tmp/openfdd_caddy_root.body -w '%{http_code}' --max-time 15 "$BASE/" || echo 000)"
if [[ "$code_root" != "200" ]]; then
  echo "FAIL GET / → HTTP $code_root (expected 200)" >&2
  fail=1
else
  echo "OK GET / → 200"
fi

code_health="$(curl -sS -o /tmp/openfdd_caddy_health.json -w '%{http_code}' --max-time 15 "$BASE/api/health" || echo 000)"
if [[ "$code_health" != "200" ]]; then
  echo "FAIL GET /api/health → HTTP $code_health (expected 200)" >&2
  fail=1
else
  echo "OK GET /api/health → 200"
  if command -v python3 >/dev/null 2>&1; then
    python3 - <<'PY'
import json
from pathlib import Path
doc = json.loads(Path("/tmp/openfdd_caddy_health.json").read_text())
assert doc.get("ok") is True or "version" in doc or "status" in doc, doc
print("OK health JSON keys:", sorted(doc)[:12])
PY
  fi
fi

exit "$fail"
