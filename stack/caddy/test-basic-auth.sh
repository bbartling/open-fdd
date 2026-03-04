#!/usr/bin/env bash
# Run this on the host where Caddy is running (e.g. 192.168.204.16).
# Usage: ./stack/caddy/test-basic-auth.sh [HOST]
# Default HOST is localhost; use 192.168.204.16 to test from another machine.
set -e
HOST="${1:-localhost}"
BASE="http://${HOST}:8088"

echo "Testing Caddy basic auth at $BASE"
echo ""

echo "1. No credentials (expect 401):"
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/")
echo "   HTTP $CODE"
[[ "$CODE" == "401" ]] && echo "   OK" || echo "   UNEXPECTED (expected 401)"

echo ""
echo "2. Wrong password (expect 401):"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -u openfdd:wrong "$BASE/")
echo "   HTTP $CODE"
[[ "$CODE" == "401" ]] && echo "   OK" || echo "   UNEXPECTED (expected 401)"

echo ""
echo "3. Correct credentials openfdd:xyz (expect 200):"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -u openfdd:xyz "$BASE/")
echo "   HTTP $CODE"
if [[ "$CODE" == "200" ]]; then
  echo "   OK - login works"
else
  echo "   FAIL - expected 200. Check Caddyfile hash and restart: docker restart openfdd_caddy"
fi
