#!/bin/sh
# Read HA options and start Open-FDD API

set -e
if [ -f /data/options.json ]; then
  export OFDD_API_KEY=$(jq -r '.api_key // empty' /data/options.json)
  export OFDD_LOG_LEVEL=$(jq -r '.log_level // "info"' /data/options.json)
  export OFDD_DB_DSN=$(jq -r '.db_url // "postgresql://postgres:postgres@core-mariadb:5432/openfdd"' /data/options.json)
  export OFDD_BACNET_SERVER_URL=$(jq -r '.bacnet_server_url // ""' /data/options.json)
  # Optional: OFDD_CORS_ORIGINS, ws is always enabled in API
fi

exec python3 -m uvicorn open_fdd.platform.api.main:app --host 0.0.0.0 --port 8000
