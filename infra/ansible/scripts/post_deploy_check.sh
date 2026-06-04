#!/usr/bin/env bash
# Insurance checks after Open-FDD ansible deploy — run from bensserver (control machine).
#
# Examples:
#   ./scripts/post_deploy_check.sh --host 192.168.204.12
#   ./scripts/post_deploy_check.sh --inventory inventory.yml --limit bacnet_pi
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ANSIBLE_DIR="$(cd "$DIR/.." && pwd)"
ROOT="$(cd "$ANSIBLE_DIR/../.." && pwd)"
HTTP_PROBES="${DIR}/http_probes.py"

HOST=""
INV="${ANSIBLE_INVENTORY:-${ANSIBLE_DIR}/inventory.yml}"
LIMIT=""
SSH_USER="${ANSIBLE_REMOTE_USER:-ben}"
SSH_OPTS=(-o ConnectTimeout=8)
SSH_CMD=(ssh "${SSH_OPTS[@]}" -o BatchMode=yes)
if [[ -n "${SSHPASS:-}" ]] && command -v sshpass >/dev/null 2>&1; then
  export SSHPASS
  SSH_CMD=(sshpass -e ssh "${SSH_OPTS[@]}" -o PreferredAuthentications=password -o PubkeyAuthentication=no)
fi
CADDY_TLS=0
AUTH_ENV="${ROOT}/workspace/auth.env.local"
FAILURES=0

usage() {
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

log_ok() { printf '  OK   %s\n' "$*"; }
log_fail() { printf '  FAIL %s\n' "$*" >&2; FAILURES=$((FAILURES + 1)); }

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage 0 ;;
    --host) HOST="$2"; shift 2 ;;
    --inventory) INV="$2"; shift 2 ;;
    --limit) LIMIT="$2"; shift 2 ;;
    --ssh-user) SSH_USER="$2"; shift 2 ;;
    --auth-env) AUTH_ENV="$2"; shift 2 ;;
    --tls) CADDY_TLS=1; shift ;;
    *) echo "Unknown option: $1" >&2; usage 1 ;;
  esac
done

INVENTORY_DOCKER_STACK=0
if [[ -n "$LIMIT" && -f "$INV" ]] && command -v ansible-inventory >/dev/null 2>&1; then
  inv_json="$(ansible-inventory -i "$INV" --host "$LIMIT" 2>/dev/null || true)"
  if [[ -n "$inv_json" ]]; then
    HOST="${HOST:-$(echo "$inv_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("ansible_host",""))' 2>/dev/null || true)}"
    inv_user="$(echo "$inv_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("ansible_user",""))' 2>/dev/null || true)"
    [[ -n "$inv_user" ]] && SSH_USER="$inv_user"
    INVENTORY_DOCKER_STACK="$(echo "$inv_json" | python3 -c 'import json,sys; print(1 if json.load(sys.stdin).get("openfdd_docker_stack") else 0)' 2>/dev/null || echo 0)"
    PROBE_SITE_ID="$(echo "$inv_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("site_id","demo") or "demo")' 2>/dev/null || echo demo)"
    POST_CHECK_REQUIRE_OLLAMA="$(echo "$inv_json" | python3 -c 'import json,sys; print(1 if json.load(sys.stdin).get("post_check_require_ollama") else 0)' 2>/dev/null || echo 0)"
    INV_ENABLE_OLLAMA="$(echo "$inv_json" | python3 -c 'import json,sys; print(1 if json.load(sys.stdin).get("enable_ollama") else 0)' 2>/dev/null || echo 0)"
    INV_DOCKER_OLLAMA="$(echo "$inv_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(0 if d.get("openfdd_docker_ollama") is False else 1)' 2>/dev/null || echo 1)"
    INV_OLLAMA_REQUIRED="$(echo "$inv_json" | python3 -c 'import json,sys; print(1 if json.load(sys.stdin).get("ollama_required") else 0)' 2>/dev/null || echo 0)"
  fi
fi
PROBE_SITE_ID="${PROBE_SITE_ID:-demo}"
INV_ENABLE_OLLAMA="${INV_ENABLE_OLLAMA:-0}"
INV_DOCKER_OLLAMA="${INV_DOCKER_OLLAMA:-1}"
INV_OLLAMA_REQUIRED="${INV_OLLAMA_REQUIRED:-0}"
# Ollama post-check only when explicitly flagged or in-stack Ollama is expected (not -e openfdd_docker_ollama=false).
if [[ "${POST_CHECK_REQUIRE_OLLAMA:-0}" != "1" ]]; then
  if [[ "${INV_OLLAMA_REQUIRED}" == "1" && "${INV_ENABLE_OLLAMA}" == "1" && "${INV_DOCKER_OLLAMA}" == "1" ]]; then
    POST_CHECK_REQUIRE_OLLAMA=1
  else
    POST_CHECK_REQUIRE_OLLAMA=0
  fi
fi
[[ -n "$HOST" ]] || { echo "Need --host IP or --limit NAME with inventory." >&2; usage 1; }

scheme=http
[[ "$CADDY_TLS" == 1 ]] && scheme=https
BASE="${scheme}://${HOST}"

if [[ -f "$AUTH_ENV" ]]; then
  # shellcheck disable=SC1090
  set -a && source "$AUTH_ENV" && set +a
fi
LOGIN_USER="${OFDD_INTEGRATOR_USER:-${OFDD_OPERATOR_USER:-}}"
LOGIN_PASS="${OFDD_INTEGRATOR_PASSWORD:-${OFDD_OPERATOR_PASSWORD:-}}"

echo "Open-FDD post-deploy check → ${HOST}"

[[ -f "$HTTP_PROBES" ]] || { log_fail "Missing ${HTTP_PROBES}"; exit 1; }

probe_args=(check "$BASE" --require-mcp --site-id "$PROBE_SITE_ID")
[[ "${POST_CHECK_REQUIRE_OLLAMA:-0}" == "1" ]] && probe_args+=(--require-ollama)
if [[ -n "$LOGIN_USER" && -n "$LOGIN_PASS" ]]; then
  probe_args+=("$LOGIN_USER" "$LOGIN_PASS")
fi
probe_json="$(python3 "$HTTP_PROBES" "${probe_args[@]}")" || probe_json='{"errors":["http_probes.py exited with error"]}'

while IFS= read -r err; do
  [[ -n "$err" ]] && log_fail "$err"
done < <(echo "$probe_json" | python3 -c 'import json,sys; [print(e) for e in json.load(sys.stdin).get("errors",[])]')

if echo "$probe_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("health_status")==200 else 1)'; then
  log_ok "Bridge API /health via Caddy (openfdd-bridge)"
fi

if echo "$probe_json" | python3 -c '
import json,sys
d=json.load(sys.stdin)
errs=d.get("errors",[])
sys.exit(0 if d.get("root_status")==200 and not any("welcome page" in e or "React shell" in e for e in errs) else 1)
'; then
  asset="$(echo "$probe_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("asset_path",""))')"
  log_ok "Production React dashboard at ${BASE}/ ${asset:+($asset)}"
fi

if echo "$probe_json" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("stack_status")==200 else 1)'; then
  log_ok "Stack health /health/stack"
fi

if echo "$probe_json" | python3 -c '
import json,sys
d=json.load(sys.stdin)
m=d.get("stack_services",{}).get("mcp_rag",{})
sys.exit(0 if m.get("configured") and m.get("status") in ("green","yellow") else 1)
'; then
  log_ok "MCP RAG enabled and healthy (via /health/stack)"
fi

if echo "$probe_json" | python3 -c 'import json,sys; d=json.load(sys.stdin).get("model_api",{}); sys.exit(0 if d.get("model_health_status")==200 and d.get("ttl_exists") and d.get("model_tree_status")==200 and d.get("model_point_count",0)>0 and d.get("model_query_engine")=="sparql" else 1)'; then
  pts="$(echo "$probe_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("model_api",{}).get("model_point_count",0))')"
  score="$(echo "$probe_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("model_api",{}).get("model_health_score",""))')"
  log_ok "BRICK model health + SPARQL tree (${pts} points, score=${score})"
fi

if echo "$probe_json" | python3 -c 'import json,sys; d=json.load(sys.stdin).get("agent",{}); sys.exit(0 if d.get("agent_context_status")==200 and d.get("mcp_enabled_in_context") else 1)'; then
  log_ok "Agent context + MCP hints for AI-assisted modeling"
fi

if echo "$probe_json" | python3 -c '
import json,sys
b=json.load(sys.stdin).get("bacnet",{})
sys.exit(0 if b.get("bacnet_tree_status")==200 and b.get("bacnet_device_count",0)>=1 and not b.get("errors") else 1)
'; then
  devs="$(echo "$probe_json" | python3 -c 'import json,sys; b=json.load(sys.stdin).get("bacnet",{}); print(b.get("bacnet_device_count",0))')"
  pts="$(echo "$probe_json" | python3 -c 'import json,sys; b=json.load(sys.stdin).get("bacnet",{}); print(b.get("bacnet_enabled_points",0))')"
  poll="$(echo "$probe_json" | python3 -c 'import json,sys; b=json.load(sys.stdin).get("bacnet",{}); print(b.get("poll_at_local_display") or b.get("poll_at_utc") or "—")')"
  log_ok "BACnet driver tree (${devs} devices, ${pts} enabled points); last poll ${poll}"
else
  log_fail "BACnet driver tree or poll health failed (see http_probes bacnet errors)"
fi

while IFS= read -r warn; do
  [[ -n "$warn" ]] && printf '  WARN %s\n' "$warn"
done < <(echo "$probe_json" | python3 -c 'import json,sys; [print(w) for w in json.load(sys.stdin).get("warnings",[])]')

ollama_ok="$(echo "$probe_json" | python3 -c 'import json,sys; d=json.load(sys.stdin).get("agent",{}); print("yes" if d.get("ollama_reachable") else "no")' 2>/dev/null || echo no)"
if [[ "$ollama_ok" == "yes" ]]; then
  model="$(echo "$probe_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("agent",{}).get("ollama_model",""))')"
  log_ok "Ollama reachable${model:+ (model ${model})}"
elif [[ "${POST_CHECK_REQUIRE_OLLAMA:-0}" == "1" ]]; then
  log_fail "Ollama required but not reachable on edge"
else
  log_ok "Ollama skipped (not supported on Pi 3 armv7l — use bensserver or Pi 4/5 64-bit)"
fi

if [[ -n "$LOGIN_USER" && -n "$LOGIN_PASS" ]]; then
  if echo "$probe_json" | python3 -c 'import json,sys; d=json.load(sys.stdin).get("login",{}); sys.exit(0 if d.get("login_status")==200 and not d.get("errors") else 1)'; then
    log_ok "Auth POST /api/auth/login for user ${LOGIN_USER}"
  fi
else
  log_ok "Auth login skipped (no credentials in ${AUTH_ENV})"
fi

if [[ "$INVENTORY_DOCKER_STACK" == "1" ]]; then
  log_ok "systemd units skipped (openfdd_docker_stack=true — health via /health/stack)"
  if command -v ssh >/dev/null 2>&1; then
    feather_b="$("${SSH_CMD[@]}" "${SSH_USER}@${HOST}" "du -sb ~/open-fdd/workspace/data/feather_store 2>/dev/null | awk '{print \$1}' || echo 0")"
    log_ok "Feather store on edge: ${feather_b:-0} bytes"
    for svc in bridge commission mcp-rag bacnet-poll; do
      cid="$("${SSH_CMD[@]}" "${SSH_USER}@${HOST}" "docker ps -q -f name=${svc} 2>/dev/null | head -1" || true)"
      if [[ -z "$cid" ]]; then
        [[ "$svc" == "bacnet-poll" ]] && continue
        log_fail "Docker service ${svc}: no running container"
        continue
      fi
      err_lines="$("${SSH_CMD[@]}" "${SSH_USER}@${HOST}" "docker logs --tail 80 \"${cid}\" 2>&1 | grep -Ei 'ERROR|Traceback|CRITICAL' | grep -v '404 Not Found' | tail -5 || true")"
      if [[ -n "$err_lines" ]]; then
        log_fail "Docker ${svc} (${cid:0:12}) log errors: ${err_lines}"
      else
        log_ok "Docker ${svc} logs clean (last 80 lines, cid ${cid:0:12})"
      fi
    done
  fi
elif command -v ssh >/dev/null 2>&1; then
  for unit in caddy openfdd-bridge openfdd-bacnet-commission openfdd-mcp-rag; do
    state="$("${SSH_CMD[@]}" "${SSH_USER}@${HOST}" "systemctl is-active ${unit}" 2>/dev/null || echo missing)"
    if [[ "$state" == "active" ]]; then
      log_ok "systemd ${unit} active"
    else
      log_fail "systemd ${unit} state=${state}"
    fi
  done
  if "${SSH_CMD[@]}" "${SSH_USER}@${HOST}" "grep -q reverse_proxy /etc/caddy/Caddyfile"; then
    log_ok "Caddyfile reverse_proxy → bridge"
  else
    log_fail "Caddyfile missing reverse_proxy (default Caddy page likely)"
  fi
  mcp_loop="$("${SSH_CMD[@]}" "${SSH_USER}@${HOST}" "curl -fsS http://127.0.0.1:8090/health 2>/dev/null || true")"
  if echo "$mcp_loop" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); sys.exit(0 if d.get("ok") else 1)' 2>/dev/null; then
    log_ok "MCP RAG loopback :8090/health OK"
  else
    log_fail "MCP RAG loopback :8090 not healthy"
  fi
fi

echo "---"
if [[ "$FAILURES" -gt 0 ]]; then
  echo "Post-deploy check FAILED (${FAILURES} issue(s))" >&2
  exit 1
fi
echo "Post-deploy check PASSED for ${HOST}"
exit 0
