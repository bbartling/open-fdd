#!/usr/bin/env bash
# Robust local/edge validation — backup before destructive steps, BACnet redo, SPARQL, Docker, pytest.
#
# Use before remote app updates to snapshot site data:
#   ./scripts/openfdd_edge_validate.sh --pre-update-backup
#
# Full bensserver bench cycle (discover → model → SPARQL → health):
#   ./scripts/openfdd_edge_validate.sh --full
#
# Preserve BACnet/model, only health + pytest (no bench reset / operational verify):
#   ./scripts/openfdd_edge_validate.sh --quick
#
# Full bench cycle (destructive BACnet/model reset + operational verify):
#   ./scripts/openfdd_edge_validate.sh --full
#   ./scripts/openfdd_edge_validate.sh          # same as --full when no flags
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV="${ROOT}/.venv"
COMPOSE=(docker compose -f docker/compose.dev.yml -f docker/compose.bench.yml)
BASE="${OPENFDD_BASE_URL:-http://127.0.0.1:8765}"
AUTH_ENV="${ROOT}/workspace/auth.env.local"
SITE_ID="${OFDD_SITE_ID:-demo}"
BUILDING_ID="${OFDD_BUILDING_ID:-bens-office}"
DEVICE="${OFDD_BENCH_DEVICE:-5007}"

PRE_BACKUP=0
FULL=0
QUICK=0
RESET_BACNET=0
RESET_MODEL=0
REBUILD=0
SKIP_DISCOVER=0
FAILURES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pre-update-backup|--backup) PRE_BACKUP=1; shift ;;
    --full|--long) FULL=1; RESET_BACNET=1; RESET_MODEL=1; shift ;;
    --quick) QUICK=1; shift ;;
    --reset-bacnet) RESET_BACNET=1; shift ;;
    --reset-model) RESET_MODEL=1; shift ;;
    --rebuild) REBUILD=1; shift ;;
    --skip-discover) SKIP_DISCOVER=1; shift ;;
    --base)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        echo "error: --base requires a URL argument" >&2
        exit 1
      fi
      BASE="$2"
      shift 2
      ;;
    -h|--help)
      sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

if [[ "$FULL" == 0 && "$QUICK" == 0 && "$PRE_BACKUP" == 0 && "$RESET_BACNET" == 0 && "$RESET_MODEL" == 0 ]]; then
  FULL=1
  RESET_BACNET=1
  RESET_MODEL=1
fi

log_ok() { printf '  OK   %s\n' "$*"; }
log_fail() { printf '  FAIL %s\n' "$*" >&2; FAILURES=$((FAILURES + 1)); }
log_step() { printf '\n==> %s\n' "$*"; }

if [[ ! -x "${VENV}/bin/python" ]]; then
  python3 -m venv "$VENV"
  "${VENV}/bin/pip" install -q -e ".[dev]" -r workspace/api/requirements.txt -r bacnet_toolshed/requirements.txt
fi

export OPENFDD_REPO_ROOT="$ROOT"
export OPENFDD_WORKSPACE_DIR="${ROOT}/workspace"
export OFDD_DESKTOP_DATA_DIR="${ROOT}/workspace/data"
export PYTHONPATH="${ROOT}:${ROOT}/workspace/api"

if [[ -f "$AUTH_ENV" ]]; then
  # shellcheck disable=SC1090
  set -a && source "$AUTH_ENV" && set +a
fi
LOGIN_USER="${OFDD_INTEGRATOR_USER:-${OFDD_OPERATOR_USER:-}}"
LOGIN_PASS="${OFDD_INTEGRATOR_PASSWORD:-${OFDD_OPERATOR_PASSWORD:-}}"

log_step "Docker maintenance"
if [[ "$REBUILD" == 1 ]]; then
  ./scripts/docker_maintenance.sh --prune --rebuild || log_fail "docker maintenance/rebuild"
else
  ./scripts/docker_maintenance.sh --prune || log_fail "docker maintenance"
fi

if [[ "$PRE_BACKUP" == 1 || "$FULL" == 1 ]]; then
  log_step "Site pack backup (${SITE_ID}/${BUILDING_ID}) — preserve for remote updates"
  ./scripts/fix_workspace_permissions.sh 2>/dev/null || true
  ./scripts/edge_site_backup.sh "$SITE_ID" "$BUILDING_ID" || log_fail "edge_site_backup"
  log_ok "backup in edge_backup/local/${SITE_ID}/${BUILDING_ID}/"
fi

if [[ "$RESET_BACNET" == 1 ]]; then
  log_step "Reset BACnet driver CSVs and poll scratch (feather latest shards)"
  rm -f "${ROOT}/workspace/bacnet/commissioning/points_discovered.csv"
  rm -f "${ROOT}/workspace/bacnet/commissioning/points.csv"
  rm -f "${ROOT}/workspace/bacnet/polls/samples.csv"
  find "${ROOT}/workspace/data/feather_store" -name 'latest.*' -delete 2>/dev/null || true
  find "${ROOT}/workspace/data/feather_store" -name 'shard-*' -delete 2>/dev/null || true
  log_ok "BACnet CSV + feather scratch cleared"
fi

if [[ "$RESET_MODEL" == 1 ]]; then
  log_step "Reset BRICK model + rules (bench import)"
  rm -f "${ROOT}/workspace/data/model.json"
  rm -f "${ROOT}/workspace/data/data_model.ttl"
  rm -f "${ROOT}/workspace/data/rules_store.json"
  log_ok "model/rules cleared (rules_py retained)"
fi

if [[ "$FULL" == 1 ]]; then
  log_step "BACnet Who-Is + full testbench (discover → points → model → rules)"
  if [[ "$SKIP_DISCOVER" == 1 ]]; then
    ./scripts/setup_local_testbench.sh --skip-discover --no-docker || log_fail "setup_local_testbench"
  else
    ./scripts/setup_local_testbench.sh --no-docker || log_fail "setup_local_testbench"
  fi
elif [[ "$RESET_MODEL" == 1 ]]; then
  "${VENV}/bin/python" scripts/setup_bench_afdd.py || log_fail "setup_bench_afdd"
fi

log_step "Ensure stack is up (bench overlay + Ollama)"
if ! "${COMPOSE[@]}" up -d bridge commission mcp-rag ollama; then
  echo "error: failed to start bench overlay stack (compose.dev.yml + compose.bench.yml)" >&2
  exit 1
fi
sleep 8
./scripts/fix_workspace_permissions.sh 2>/dev/null || true

log_step "Public check-engine API (no auth - home / faults dashboard)"
if public_out="$("${VENV}/bin/python" "${ROOT}/infra/ansible/scripts/http_probes.py" check-public "$BASE" 2>&1)"; then
  log_ok "public check-engine endpoints (200, no Bearer)"
  echo "$public_out" | "${VENV}/bin/python" -c 'import json,sys; d=json.load(sys.stdin); [print(f"    {p}: {c}") for p,c in sorted((d.get("endpoints") or {}).items())]' 2>/dev/null || true
else
  log_fail "public check-engine endpoints"
  echo "$public_out" | head -30 >&2 || true
fi

log_step "Feather compact (Arrow historian)"
if docker compose -f docker/compose.dev.yml -f docker/compose.bench.yml exec -T bridge \
  python -m openfdd_bridge.feather_store --compact 2>&1; then
  log_ok "feather_store --compact"
else
  if "${VENV}/bin/python" -m openfdd_bridge.feather_store --compact 2>&1; then
    log_ok "feather_store --compact (host venv)"
  else
    log_fail "feather_store --compact"
  fi
fi

if [[ -n "$LOGIN_USER" && -n "$LOGIN_PASS" ]]; then
  log_step "API: SPARQL model probes + sync-ttl (authenticated)"
  api_py="${ROOT}/infra/ansible/scripts/bench_operational_verify.sh"

  if probe_out="$("${VENV}/bin/python" "${ROOT}/infra/ansible/scripts/http_probes.py" check \
    "$BASE" "$LOGIN_USER" "$LOGIN_PASS" --require-mcp --require-ollama 2>&1)"; then
    log_ok "http_probes (SPARQL + scope/plot + MCP + Ollama)"
    echo "$probe_out" | "${VENV}/bin/python" -c "
import json,sys
d=json.load(sys.stdin)
m=d.get('model_api') or {}
print('    model_health:', m.get('model_health_status'), 'tree:', m.get('model_tree_status'), 'engine:', m.get('model_query_engine'))
ag=d.get('agent') or {}
print('    ollama_reachable:', ag.get('ollama_reachable'), 'model:', ag.get('ollama_model'))
ui=d.get('integrator_ui') or {}
print('    model_scope:', ui.get('model_scope_status'), 'equipment:', ui.get('model_scope_equipment_count'))
print('    timeseries:', ui.get('timeseries_readings_status'))
" 2>/dev/null || true
  else
    log_fail "http_probes failed"
    echo "$probe_out" | head -40 >&2 || true
  fi

  log_step "Ollama hello chat probe"
  if hello_out="$("${VENV}/bin/python" -c "
import json, sys
sys.path.insert(0, '${ROOT}/infra/ansible/scripts')
from http_probes import check_login, check_ollama_hello_chat
base = '${BASE}'
login = check_login(base, '${LOGIN_USER}', '${LOGIN_PASS}')
if login.get('errors'):
    print(json.dumps({'errors': login['errors']}))
    sys.exit(0)
out = check_ollama_hello_chat(base, login['token'])
print(json.dumps(out))
" 2>&1)"; then
    if echo "$hello_out" | "${VENV}/bin/python" -c "
import json,sys
d=json.load(sys.stdin)
sys.exit(0 if not d.get('errors') else 1)
" 2>/dev/null; then
      preview="$(echo "$hello_out" | "${VENV}/bin/python" -c "import json,sys; print((json.load(sys.stdin).get('reply_preview') or '')[:80])" 2>/dev/null || true)"
      log_ok "ollama hello chat${preview:+ — ${preview}}"
    else
      log_fail "ollama hello chat"
      echo "$hello_out" | head -20 >&2 || true
    fi
  else
    log_fail "ollama hello chat probe crashed"
  fi

  if [[ "$FULL" == 1 && -f "$api_py" ]]; then
    log_step "Bench operational verify - discover, import, poll, FDD"
    bench_args=(--host 127.0.0.1 --port 8765 --wait-minutes 2)
    if [[ "${SKIP_WAIT:-0}" == 1 ]]; then
      bench_args+=(--skip-wait)
    fi
    RUN_WAIT_MINUTES=2 "${api_py}" "${bench_args[@]}" || log_fail "bench_operational_verify"
  fi
else
  log_fail "missing credentials in ${AUTH_ENV}"
fi

log_step "pytest (bridge security + SPARQL + playground subprocess)"
export PYTHONPATH="${ROOT}:${ROOT}/workspace/api"
if "${VENV}/bin/pytest" -q \
  tests/workspace_bridge/test_playground_subprocess.py \
  tests/workspace_bridge/test_zone_temp_analytics.py \
  tests/workspace_bridge/test_security.py \
  tests/workspace_bridge/test_fault_catalog.py \
  tests/test_http_probes_sparql.py \
  tests/workspace_bridge/test_model_building.py \
  tests/workspace_bridge/test_feather_store.py \
  tests/workspace_bridge/test_fdd_batch_cache.py \
  tests/workspace_bridge/test_bacnet_poll_pipeline.py 2>&1; then
  log_ok "pytest subset passed"
else
  log_fail "pytest subset"
fi

log_step "stack_health_check"
if OPENFDD_BASE_URL="$BASE" ./scripts/stack_health_check.sh --require-ollama; then
  log_ok "stack_health_check"
else
  log_fail "stack_health_check"
fi

log_step "Docker error scan (last 20m)"
for svc in bridge commission mcp-rag ollama; do
  cid="$(docker compose -f docker/compose.dev.yml ps -q "$svc" 2>/dev/null || true)"
  [[ -n "$cid" ]] || continue
  n="$(docker logs --since 20m "$cid" 2>&1 | grep -ciE 'ModuleNotFoundError|Traceback|CRITICAL' || true)"
  if [[ "${n:-0}" -eq 0 ]]; then
    log_ok "${svc} logs clean"
  else
    log_fail "${svc} has ${n} critical log lines"
    docker logs --tail 8 "$cid" 2>&1 | sed 's/^/    /' || true
  fi
done

echo ""
if [[ "$FAILURES" -gt 0 ]]; then
  echo "VALIDATE FAILED (${FAILURES} step(s))" >&2
  exit 1
fi
echo "VALIDATE OK — ${SITE_ID}/${BUILDING_ID} @ ${BASE}"
echo "  GUI: ${BASE}/  (home/faults public; integrator login for BACnet/Agent — workspace/auth.env.local)"
echo "  Arrow historian: docs/architecture/arrow_data_plane.md"
echo "  Site backup: edge_backup/local/${SITE_ID}/${BUILDING_ID}/"
echo "  Remote update: ./scripts/edge_site_backup.sh ${SITE_ID} ${BUILDING_ID} before deploy"
echo "  Restore:       ./scripts/edge_site_apply.sh ${SITE_ID} ${BUILDING_ID} --from-backup"
