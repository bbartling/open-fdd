#!/usr/bin/env bash
# Post-deploy / post-up health gate for Open-FDD Docker dev stack and future edge sites.
#
#   ./scripts/stack_health_check.sh
#   ./scripts/stack_health_check.sh --require-ollama
#   OPENFDD_BASE_URL=http://192.168.1.10 ./scripts/stack_health_check.sh
#   OPENFDD_HEALTH_MIN_MODEL_POINTS=5 OPENFDD_HEALTH_MIN_MODEL_EQUIPMENT=1 ./scripts/stack_health_check.sh
# Probes: /api/model/health, /api/model/sites, /api/model/tree, /api/model/graph (SPARQL)
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f docker/compose.dev.yml)
BASE="${OPENFDD_BASE_URL:-http://127.0.0.1:8765}"
REQUIRE_OLLAMA=0
FAILURES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --require-ollama) REQUIRE_OLLAMA=1; shift ;;
    --base) BASE="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

log_ok() { printf '  OK   %s\n' "$*"; }
log_fail() { printf '  FAIL %s\n' "$*" >&2; FAILURES=$((FAILURES + 1)); }
log_warn() { printf '  WARN %s\n' "$*"; }

# shellcheck source=scripts/docker_container_gate.sh
source "${ROOT}/scripts/docker_container_gate.sh"
docker_gate_reset_failures

echo "Open-FDD stack health → ${BASE}"

echo "==> Docker containers"
docker_gate_check_compose docker/compose.dev.yml bridge commission mcp-rag
FAILURES=$((FAILURES + DOCKER_GATE_FAILURES))

ollama_cid="$("${COMPOSE[@]}" --profile ai ps -q ollama 2>/dev/null || true)"
if [[ -n "$ollama_cid" ]]; then
  docker_gate_check_cid ollama "$ollama_cid"
  FAILURES=$((FAILURES + DOCKER_GATE_FAILURES))
  docker_gate_reset_failures
elif [[ "$REQUIRE_OLLAMA" == 1 ]]; then
  log_fail "ollama container required but not started (use: docker compose --profile ai up -d)"
fi

AUTH_ENV="${ROOT}/workspace/auth.env.local"
if [[ -f "$AUTH_ENV" ]]; then
  # shellcheck disable=SC1090
  set -a && source "$AUTH_ENV" && set +a
fi
USER="${OFDD_INTEGRATOR_USER:-${OFDD_OPERATOR_USER:-}}"
PASS="${OFDD_INTEGRATOR_PASSWORD:-${OFDD_OPERATOR_PASSWORD:-}}"
if [[ -z "$USER" || -z "$PASS" ]]; then
  log_fail "missing credentials in workspace/auth.env.local"
  exit 1
fi

PROBE_ARGS=(check "$BASE" "$USER" "$PASS" --require-mcp)
if [[ "$REQUIRE_OLLAMA" == 1 ]]; then
  PROBE_ARGS+=(--require-ollama)
fi

echo "==> HTTP / API probes"
if probe_json="$(python3 "${ROOT}/infra/ansible/scripts/http_probes.py" "${PROBE_ARGS[@]}" 2>&1)"; then
  log_ok "http_probes passed"
  echo "$probe_json" | python3 -c "
import json,sys
d=json.load(sys.stdin)
ma=d.get('model_api') or {}
ag=d.get('agent') or {}
ch=d.get('agent_chat') or {}
if ma.get('model_health_score') is not None:
    print('       model_health score=%s status=%s ttl=%s' % (ma.get('model_health_score'), ma.get('model_health_status_label'), ma.get('ttl_exists')))
if ma.get('model_point_count') is not None:
    eq = ma.get('model_equipment_count', ma.get('model_equipment_count_tree'))
    print('       sparql_points=%s equipment=%s site=%s' % (ma.get('model_point_count'), eq, ma.get('active_site_id','')))
if ag.get('mcp_enabled_in_context') is not None:
    print('       mcp_enabled=%s' % ag.get('mcp_enabled_in_context'))
if ag.get('ollama_reachable') is not None:
    print('       ollama_reachable=%s' % ag.get('ollama_reachable'))
if ch.get('reply_preview'):
    print('       chat_preview=%r' % ch.get('reply_preview'))
" 2>/dev/null || true
else
  log_fail "http_probes failed"
  echo "$probe_json" | python3 -c 'import json,sys
try:
  d=json.loads(sys.stdin.read())
  [print("       ",e) for e in d.get("errors",[])]
except Exception:
  print(sys.stdin.read()[:800])
' 2>/dev/null || echo "$probe_json" | tail -20
  FAILURES=$((FAILURES + 1))
fi

echo "==> In-container MCP reachability"
bridge_cid="$("${COMPOSE[@]}" ps -q bridge 2>/dev/null || true)"
if [[ -n "$bridge_cid" ]]; then
  mcp_ok=0
  for mcp_url in "http://mcp-rag:8090/health" "http://127.0.0.1:8090/health"; do
    if docker exec "$bridge_cid" python3 -c \
      "import urllib.request; urllib.request.urlopen('${mcp_url}', timeout=5)" \
      >/dev/null 2>&1; then
      log_ok "bridge → ${mcp_url}"
      mcp_ok=1
      break
    fi
  done
  if [[ "$mcp_ok" == 0 ]]; then
    log_fail "bridge cannot reach MCP (tried mcp-rag:8090 and 127.0.0.1:8090)"
  fi
fi

if [[ "$FAILURES" -gt 0 ]]; then
  echo "Stack health check FAILED (${FAILURES} issue(s))" >&2
  exit 1
fi
echo "Stack health check PASSED"
exit 0
