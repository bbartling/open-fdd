#!/usr/bin/env bash
set -euo pipefail

# Verifies weather points are available for at least one site.
# Exit 0 when weather points exist; non-zero otherwise.

API_BASE="${1:-http://localhost:8000}"
API_BASE="${API_BASE%/}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STACK_ENV="$REPO_ROOT/stack/.env"

if [[ -z "${OFDD_API_KEY:-}" && -f "$STACK_ENV" ]]; then
  # shellcheck disable=SC1090
  source "$STACK_ENV" 2>/dev/null || true
fi

auth_args=()
if [[ -n "${OFDD_API_KEY:-}" ]]; then
  auth_args=(-H "Authorization: Bearer ${OFDD_API_KEY}")
fi

sites_json="$(curl -sf "${auth_args[@]}" "$API_BASE/sites")" || exit 1

site_id="$(
  python3 - <<'PY' "$sites_json"
import json
import sys

raw = sys.argv[1]
try:
    sites = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)

if isinstance(sites, list) and sites:
    first = sites[0] or {}
    print(first.get("id", ""))
else:
    print("")
PY
)"

[[ -n "$site_id" ]] || exit 1

points_json="$(curl -sf "${auth_args[@]}" "$API_BASE/points?site_id=$site_id")" || exit 1

python3 - <<'PY' "$points_json"
import json
import sys

raw = sys.argv[1]
try:
    points = json.loads(raw)
except Exception:
    raise SystemExit(1)

weather_ids = {
    "temp_f",
    "rh_pct",
    "dew_point_f",
    "wind_speed_mph",
    "wind_gust_mph",
    "wind_dir_deg",
    "shortwave_wm2",
    "cloud_pct",
}

for p in points if isinstance(points, list) else []:
    ext = str((p or {}).get("external_id", "")).strip().lower()
    if ext in weather_ids:
        raise SystemExit(0)

raise SystemExit(1)
PY
