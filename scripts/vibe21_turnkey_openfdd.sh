#!/usr/bin/env bash
# Turnkey: master_build → ensure portable export → pull tip GHCR → up react-ot → smoke vibe21 APIs.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export VIBE21_ORACLE="${VIBE21_ORACLE:-/home/ben/py-bacnet-stacks-playground/vibe_code_apps_21}"
export OPENFDD_JOB_ROOT="${OPENFDD_JOB_ROOT:-$ROOT/workspace/vibe21_jobs}"
JOB_ID="${JOB_ID:-b100-ops11}"

echo "==> master_build (reuse-champion unless MASTER_BUILD_FORCE=1)"
if [[ "${MASTER_BUILD_FORCE:-0}" == "1" ]]; then
  ./scripts/vibe21_master_build.sh --job-id "$JOB_ID" --profile pilot
else
  ./scripts/vibe21_master_build.sh --job-id "$JOB_ID" --profile pilot --reuse-champion
fi
python3 ./scripts/vibe21_export_champion_portable.py \
  --model-dir "$OPENFDD_JOB_ROOT/$JOB_ID/models/modelrel_demand_hourly"

if [[ "${SKIP_PULL:-0}" != "1" ]]; then
  TIP="$(git rev-parse --short=7 HEAD)"
  export OPENFDD_IMAGE_TAG="${OPENFDD_IMAGE_TAG:-sha-$TIP}"
  echo "==> pull/up react-ot pin=$OPENFDD_IMAGE_TAG"
  ./scripts/openfdd_stack_pull.sh react-ot || true
  OPENFDD_REACT_UI=1 OPENFDD_UI_GENERATION_DEFAULT=react \
    ./scripts/openfdd_stack_up.sh react-ot --no-pull || \
    ./scripts/openfdd_stack_up.sh react-ot
fi

echo "==> vibe21 API smoke"
curl -fsS "http://127.0.0.1:8080/api/v1/health" | tee /tmp/vibe21_health.json
curl -fsS "http://127.0.0.1:8080/api/v1/models" | head -c 400; echo
curl -fsS -X POST "http://127.0.0.1:8080/api/v1/predict/demand_hourly" \
  -H 'content-type: application/json' \
  -d '{"strategy_id":"baseline","oat_c":32,"rh_pct":55,"hour_ending":15}' \
  | tee /tmp/vibe21_predict.json
curl -fsS -o /dev/null -w 'unity_index=%{http_code}\n' \
  "http://127.0.0.1:8080/twins/twin_ops11/builds/unitybuild_liberty100/"
curl -fsS -o /dev/null -w 'spa_twin=%{http_code}\n' "http://127.0.0.1:3000/twin" || true

echo "OK turnkey smoke complete"
