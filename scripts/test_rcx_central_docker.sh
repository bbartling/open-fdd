#!/usr/bin/env bash
# Smoke test OpenFDD RCx Central Docker stack (cross-platform)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="docker compose -f $ROOT/docker/rcx-central/docker-compose.yml"

export OPENFDD_IMAGE_TAG="${OPENFDD_IMAGE_TAG:-local}"
$COMPOSE build
$COMPOSE up -d
trap '$COMPOSE down' EXIT

for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8060/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS http://127.0.0.1:8060/health | grep -q ok
curl -fsS http://127.0.0.1:8050/ | head -c 200 >/dev/null
$COMPOSE exec -T rcx-central-api python -c "from pathlib import Path; p=Path('/app/portfolio/data/reports'); p.mkdir(exist_ok=True); (p/'_write_test').write_text('ok'); assert (p/'_write_test').read_text()=='ok'"
echo "RCx Central Docker smoke: PASS"
