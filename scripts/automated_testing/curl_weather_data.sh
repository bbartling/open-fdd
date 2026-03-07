#!/usr/bin/env bash
# Curl the backend the same way the frontend gets weather data (POST /download/csv with point_ids).
# Run from repo root with stack up. Uses stack/.env for OFDD_API_KEY.
# Usage: ./scripts/curl_weather_data.sh [BASE_URL]

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$REPO_ROOT/stack/.env"
BASE_URL="${1:-http://localhost:8000}"
BASE_URL="${BASE_URL%/}"

if [[ -f "$ENV_FILE" ]]; then
  OFDD_API_KEY=$(grep -E '^OFDD_API_KEY=' "$ENV_FILE" | cut -d= -f2- | tr -d '"' | tr -d "'")
  export OFDD_API_KEY
fi
if [[ -z "${OFDD_API_KEY:-}" ]]; then
  echo "Warning: OFDD_API_KEY not set. If the API requires auth, requests will 401." >&2
fi
AUTH_HEADER=""
if [[ -n "${OFDD_API_KEY:-}" ]]; then
  AUTH_HEADER="Authorization: Bearer $OFDD_API_KEY"
fi

echo "=== 1. GET /sites ==="
CURL_AUTH=()
[[ -n "$AUTH_HEADER" ]] && CURL_AUTH=(-H "$AUTH_HEADER")
SITES_JSON=$(curl -s "${CURL_AUTH[@]}" "$BASE_URL/sites")
echo "$SITES_JSON" | head -c 500
echo ""
SITE_ID=$(echo "$SITES_JSON" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    sites = d if isinstance(d, list) else []
    if not sites:
        print('default')
    else:
        print(sites[0].get('id', 'default'))
except Exception:
    print('default')
" 2>/dev/null || echo "default")
echo "Using site_id: $SITE_ID"
echo ""

echo "=== 2. GET /points?site_id=$SITE_ID (first 2000) ==="
POINTS_JSON=$(curl -s "${CURL_AUTH[@]}" "$BASE_URL/points?site_id=$SITE_ID&limit=2000")
echo "$POINTS_JSON" | head -c 400
echo "..."

# Weather external_ids same as WebWeatherPage
WEATHER_IDS=("temp_f" "rh_pct" "dewpoint_f" "wind_mph" "gust_mph" "wind_dir_deg" "shortwave_wm2" "direct_wm2" "diffuse_wm2" "gti_wm2" "cloud_pct")
POINT_IDS=$(echo "$POINTS_JSON" | python3 -c "
import sys, json
ids = ['temp_f','rh_pct','dewpoint_f','wind_mph','gust_mph','wind_dir_deg','shortwave_wm2','direct_wm2','diffuse_wm2','gti_wm2','cloud_pct']
try:
    d = json.load(sys.stdin)
    points = d if isinstance(d, list) else []
    out = [p['id'] for p in points if p.get('external_id') in ids]
    print(json.dumps(out))
except Exception as e:
    print('[]')
" 2>/dev/null || echo "[]")

WEATHER_COUNT=$(echo "$POINT_IDS" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
echo "Weather point_ids ($WEATHER_COUNT): $POINT_IDS"
if [[ "$WEATHER_COUNT" -eq 0 ]]; then
  echo ""
  echo ">>> No Open-Meteo points (temp_f, rh_pct, etc.) for this site. Frontend will show no weather charts. <<<"
  echo "    Possible causes:"
  echo "    - Config → open_meteo_site_id may point to a different site; try that site in the selector."
  echo "    - Run FDD or start the weather scraper so Open-Meteo data is fetched and points created."
  echo "    - GET /points for this site only returned: $(echo "$POINTS_JSON" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    points = d if isinstance(d, list) else []
    ext = [p.get('external_id') for p in points[:15]]
    print(', '.join(ext) + (' ...' if len(points) > 15 else ''))
except Exception: print('(parse error)')
" 2>/dev/null)"
  echo ""
fi
echo ""

# Date range: last 7 days (same as frontend default)
END_DATE=$(python3 -c "from datetime import date; print(date.today())")
START_DATE=$(python3 -c "from datetime import date, timedelta; print(date.today() - timedelta(days=7))")
echo "=== 3. POST /download/csv (same as frontend: site_id, start_date, end_date, format=long, point_ids) ==="
BODY=$(printf '%s' "{\"site_id\":\"$SITE_ID\",\"start_date\":\"$START_DATE\",\"end_date\":\"$END_DATE\",\"format\":\"long\",\"point_ids\":$POINT_IDS}")
echo "Body: $BODY"
echo ""

CSV_RESPONSE=$(curl -s -X POST -H "Content-Type: application/json" "${CURL_AUTH[@]}" -d "$BODY" "$BASE_URL/download/csv")
LINES=$(echo "$CSV_RESPONSE" | grep -c . 2>/dev/null || echo 0)
echo "Response: $LINES lines"
if [[ "$LINES" -gt 0 ]]; then
  echo "--- First 5 lines ---"
  echo "$CSV_RESPONSE" | head -5
  echo "--- Last 3 lines ---"
  echo "$CSV_RESPONSE" | tail -3
else
  echo "--- Full response (no newlines or empty) ---"
  echo "$CSV_RESPONSE" | head -c 500
fi
echo ""
if [[ "$WEATHER_COUNT" -eq 0 ]]; then
  echo "Result: This site has no weather points. CSV above is all-site timeseries (e.g. BACnet), not Open-Meteo. Create weather data by running FDD or the weather scraper and ensure Config → open_meteo_site_id matches this site (or switch site in the UI)."
  exit 1
fi
if [[ "$LINES" -lt 2 ]]; then
  echo "Result: Weather points exist but no timeseries in range. Try a wider date range or run a weather fetch."
  exit 1
fi
echo "Result: Backend returned weather CSV ($LINES lines). If the frontend still shows nothing, hard-refresh and check date range."
exit 0
