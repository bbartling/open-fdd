#!/usr/bin/env bash
# Insurance checks after Open-FDD ansible deploy — run from bensserver (control machine).
#
# Examples:
#   ./scripts/post_deploy_check.sh --host 192.168.204.12
#   ./scripts/post_deploy_check.sh --inventory inventory.yml --limit bacnet_pi
#   ./scripts/post_deploy_check.sh --limit acme_vm_bbartling --full   # Acme long HTTP suite
#   ./scripts/post_deploy_check.sh --limit acme_vm_bbartling --http-only
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ANSIBLE_DIR="$(cd "$DIR/.." && pwd)"
ROOT="$(cd "$ANSIBLE_DIR/../.." && pwd)"
SECRETS_DIR="${ANSIBLE_DIR}/secrets"
HTTP_PROBES="${DIR}/http_probes.py"

HOST=""
INV="${ANSIBLE_INVENTORY:-${ANSIBLE_DIR}/inventory.yml}"
LIMIT=""
SSH_USER="${ANSIBLE_REMOTE_USER:-ben}"
FULL_CHECK=0
HTTP_ONLY=0
CADDY_TLS=0
AUTH_ENV="${ROOT}/workspace/auth.env.local"
FAILURES=0

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

log_ok() { printf '  OK   %s\n' "$*"; }
log_warn() { printf '  WARN %s\n' "$*"; }
log_fail() { printf '  FAIL %s\n' "$*" >&2; FAILURES=$((FAILURES + 1)); }

# Map inventory --limit host → secrets/<alias>.env.local (same as deploy.sh).
load_edge_secrets() {
  local limit="${1:-}"
  local secrets_file=""
  if [[ -n "$limit" && -f "${SECRETS_DIR}/${limit}.env.local" ]]; then
    secrets_file="${SECRETS_DIR}/${limit}.env.local"
  else
    case "$limit" in
      acme_vm_bbartling) secrets_file="${SECRETS_DIR}/acme.env.local" ;;
      bacnet_pi) secrets_file="${SECRETS_DIR}/bacnet_pi.env.local" ;;
    esac
  fi
  if [[ -n "$secrets_file" && -f "$secrets_file" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$secrets_file"
    set +a
    export SSHPASS="${SSHPASS:-}"
  fi
}

build_ssh_cmd() {
  SSH_OPTS=(-o ConnectTimeout=8)
  SSH_CMD=(ssh "${SSH_OPTS[@]}" -o BatchMode=yes)
  if [[ -n "${SSHPASS:-}" ]] && command -v sshpass >/dev/null 2>&1; then
    export SSHPASS
    SSH_CMD=(sshpass -e ssh "${SSH_OPTS[@]}" -o PreferredAuthentications=password -o PubkeyAuthentication=no)
  fi
}

# Run remote command; suppress ssh noise, return captured stdout or empty on failure.
ssh_remote() {
  local out rc
  out="$("${SSH_CMD[@]}" "${SSH_USER}@${HOST}" "$@" 2>/dev/null)" || rc=$?
  if [[ "${rc:-0}" -ne 0 ]]; then
    return 1
  fi
  printf '%s' "$out"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage 0 ;;
    --host) HOST="$2"; shift 2 ;;
    --inventory) INV="$2"; shift 2 ;;
    --limit) LIMIT="$2"; shift 2 ;;
    --ssh-user) SSH_USER="$2"; shift 2 ;;
    --auth-env) AUTH_ENV="$2"; shift 2 ;;
    --full) FULL_CHECK=1; shift ;;
    --http-only) HTTP_ONLY=1; shift ;;
    --tls) CADDY_TLS=1; shift ;;
    *) echo "Unknown option: $1" >&2; usage 1 ;;
  esac
done

[[ -n "$LIMIT" ]] && load_edge_secrets "$LIMIT"
build_ssh_cmd

INVENTORY_DOCKER_STACK=0
EXPECTED_IMAGE_TAG=""
if [[ -n "$LIMIT" && -f "$INV" ]] && command -v ansible-inventory >/dev/null 2>&1; then
  inv_json="$(ansible-inventory -i "$INV" --host "$LIMIT" 2>/dev/null || true)"
  if [[ -n "$inv_json" ]]; then
    read_inv() {
      echo "$inv_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print($1)" 2>/dev/null || true
    }
    HOST="${HOST:-$(read_inv 'd.get("ansible_host","")')}"
    inv_user="$(read_inv 'd.get("ansible_user","")')"
    [[ -n "$inv_user" ]] && SSH_USER="$inv_user"
    INVENTORY_DOCKER_STACK="$(read_inv '1 if d.get("openfdd_docker_stack") else 0')"
    PROBE_SITE_ID="$(read_inv 'd.get("site_id","demo") or "demo"')"
    POST_CHECK_REQUIRE_OLLAMA="$(read_inv '1 if d.get("post_check_require_ollama") else 0')"
    INV_ENABLE_OLLAMA="$(read_inv '1 if d.get("enable_ollama") else 0')"
    INV_DOCKER_OLLAMA="$(read_inv '0 if d.get("openfdd_docker_ollama") is False else 1')"
    INV_OLLAMA_REQUIRED="$(read_inv '1 if d.get("ollama_required") else 0')"
    EXPECTED_IMAGE_TAG="$(read_inv 'd.get("openfdd_docker_image_tag","") or ""')"
    export OPENFDD_HEALTH_MIN_MODEL_POINTS="$(read_inv 'd.get("post_check_min_model_points", 0) or 0')"
    export OPENFDD_HEALTH_MIN_BACNET_DEVICES="$(read_inv 'd.get("post_check_min_bacnet_devices", 1) or 1')"
    export OPENFDD_HEALTH_MIN_BACNET_POINTS="$(read_inv 'd.get("post_check_min_bacnet_points", 1) or 1')"
    export OPENFDD_POST_CHECK_MIN_RULES="$(read_inv 'd.get("post_check_min_saved_rules", 1) or 1')"
    export OPENFDD_POST_CHECK_MIN_BOUND_POINTS="$(read_inv 'd.get("post_check_min_bound_points", 0) or 0')"
    if [[ "$(read_inv '1 if d.get("post_check_full") else 0')" == "1" ]]; then
      FULL_CHECK=1
    fi
  fi
fi
PROBE_SITE_ID="${PROBE_SITE_ID:-demo}"
INV_ENABLE_OLLAMA="${INV_ENABLE_OLLAMA:-0}"
INV_DOCKER_OLLAMA="${INV_DOCKER_OLLAMA:-1}"
INV_OLLAMA_REQUIRED="${INV_OLLAMA_REQUIRED:-0}"
[[ -n "$EXPECTED_IMAGE_TAG" ]] && export OPENFDD_EXPECTED_IMAGE_TAG="$EXPECTED_IMAGE_TAG"

if [[ "${INV_DOCKER_OLLAMA}" == "0" ]]; then
  POST_CHECK_REQUIRE_OLLAMA=0
elif [[ "${POST_CHECK_REQUIRE_OLLAMA:-0}" != "1" ]]; then
  if [[ "${INV_OLLAMA_REQUIRED}" == "1" && "${INV_ENABLE_OLLAMA}" == "1" ]]; then
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
# Remote edge probes: secrets/acme.env.local (or host alias) wins over control-machine auth.env.local
if [[ -n "${ACME_INTEGRATOR_USER:-}" && -n "${ACME_INTEGRATOR_PASSWORD:-}" ]]; then
  LOGIN_USER="$ACME_INTEGRATOR_USER"
  LOGIN_PASS="$ACME_INTEGRATOR_PASSWORD"
fi
if [[ -n "${ACME_SITE_ID:-}" ]]; then
  PROBE_SITE_ID="$ACME_SITE_ID"
fi

mode_label="standard"
[[ "$FULL_CHECK" == "1" ]] && mode_label="full (Acme long HTTP suite)"
[[ "$HTTP_ONLY" == "1" ]] && mode_label="${mode_label} + http-only"
echo "Open-FDD post-deploy check → ${HOST} [${mode_label}]"

[[ -f "$HTTP_PROBES" ]] || { log_fail "Missing ${HTTP_PROBES}"; exit 1; }

probe_args=(check "$BASE" --require-mcp --site-id "$PROBE_SITE_ID")
[[ "${POST_CHECK_REQUIRE_OLLAMA:-0}" == "1" ]] && probe_args+=(--require-ollama)
[[ "$FULL_CHECK" == "1" ]] && probe_args+=(--full)
if [[ -n "$LOGIN_USER" && -n "$LOGIN_PASS" ]]; then
  probe_args+=("$LOGIN_USER" "$LOGIN_PASS")
fi
# Capture JSON even when probes return exit 1 (errors in payload); do not use cmd || fallback (loses stdout).
probe_json="$(python3 "$HTTP_PROBES" "${probe_args[@]}" 2>/dev/null)" || true
if ! echo "$probe_json" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null; then
  probe_json='{"errors":["http_probes.py produced no JSON"]}'
fi

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
  local_asset=""
  if [[ -f "${ROOT}/workspace/api/static/app/index.html" ]]; then
    local_asset="$(grep -oE 'index-[^"]+\.js' "${ROOT}/workspace/api/static/app/index.html" | head -1 || true)"
  fi
  asset_base="${asset##*/}"
  if [[ -n "$local_asset" && -n "$asset_base" && "$asset_base" != "$local_asset" ]]; then
    log_warn "Edge UI bundle ${asset_base} ≠ bensserver build ${local_asset} — run: OPENFDD_IMAGE_TAG=${EXPECTED_IMAGE_TAG:-<tag>} ${ROOT}/scripts/upgrade_edge_full.sh --limit ${LIMIT:-<host>}"
  fi
  if [[ "$asset" == *TRH4YIfA* ]]; then
    log_warn "Known stale Acme UI (TRH4YIfA) — deploy UI: cd infra/ansible && ./deploy.sh ui --limit ${LIMIT:-acme_vm_bbartling}"
  fi
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

if [[ "$FULL_CHECK" == "1" ]]; then
  rev_status="$(echo "$probe_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("stack_revision",{}).get("stack_revision_status",0))')"
  rev_tag="$(echo "$probe_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("stack_revision",{}).get("image_tag",""))')"
  if [[ "$rev_status" == "200" && -n "$rev_tag" ]]; then
    sha="$(echo "$probe_json" | python3 -c 'import json,sys; s=json.load(sys.stdin).get("stack_revision",{}).get("git_sha",""); print(s[:12] if s else "")')"
    log_ok "Container image tag ${rev_tag}${sha:+ (git ${sha})}${EXPECTED_IMAGE_TAG:+ [inventory ${EXPECTED_IMAGE_TAG}]}"
  elif [[ "$rev_status" == "200" ]]; then
    log_warn "Container image tag not reported by bridge (upgrade image for OPENFDD_IMAGE_TAG in /health/stack)"
  fi

  if echo "$probe_json" | python3 -c '
import json,sys
f=json.load(sys.stdin).get("fdd_operational",{})
sys.exit(0 if f.get("rules_saved_status")==200 and not f.get("errors") else 1)
'; then
    rules="$(echo "$probe_json" | python3 -c 'import json,sys; f=json.load(sys.stdin).get("fdd_operational",{}); print(f.get("rules_enabled_count",0))')"
    bound="$(echo "$probe_json" | python3 -c 'import json,sys; f=json.load(sys.stdin).get("fdd_operational",{}); print(f.get("rules_binding_refs", f.get("rules_bound_point_refs",0)))')"
    log_ok "FDD saved rules (${rules} enabled, ${bound} binding refs)"
  fi

  if echo "$probe_json" | python3 -c '
import json,sys
f=json.load(sys.stdin).get("fdd_operational",{})
sys.exit(0 if f.get("rules_assignments_status")==200 else 1)
'; then
    rows="$(echo "$probe_json" | python3 -c 'import json,sys; f=json.load(sys.stdin).get("fdd_operational",{}); print(f.get("assignment_point_rows",0))')"
    log_ok "FDD assignments API (${rows} point rows for site ${PROBE_SITE_ID})"
  fi

  comm_status="$(echo "$probe_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("fdd_operational",{}).get("commissioning_export_status",0))')"
  if [[ "$comm_status" == "200" ]]; then
    cpts="$(echo "$probe_json" | python3 -c 'import json,sys; f=json.load(sys.stdin).get("fdd_operational",{}); print(f.get("commissioning_point_count",0))')"
    crules="$(echo "$probe_json" | python3 -c 'import json,sys; f=json.load(sys.stdin).get("fdd_operational",{}); print(f.get("commissioning_fdd_rules_count",0))')"
    tagged="$(echo "$probe_json" | python3 -c 'import json,sys; f=json.load(sys.stdin).get("fdd_operational",{}); print(f.get("commissioning_points_with_rules",0))')"
    linked="$(echo "$probe_json" | python3 -c 'import json,sys; f=json.load(sys.stdin).get("fdd_operational",{}); print(f.get("commissioning_points_with_linked_names",0))')"
    log_ok "Commissioning export (${cpts} points, ${crules} rules, ${tagged} tagged, ${linked} with Rule Lab names)"
    if [[ "${tagged:-0}" -gt 0 && "${linked:-0}" -lt "${tagged:-0}" ]]; then
      log_warn "Some pinned points lack fdd_rules_linked — upgrade bridge for readable export"
    fi
  elif [[ "$comm_status" == "404" ]]; then
    log_warn "Commissioning export HTTP 404 — upgrade bridge image for Model & assignments bundle"
  fi

  if echo "$probe_json" | python3 -c '
import json,sys
f=json.load(sys.stdin).get("fdd_operational",{})
sys.exit(0 if f.get("building_insight_status")==200 else 1)
'; then
    log_ok "Building insight briefing (Ollama path)"
  fi

  if echo "$probe_json" | python3 -c '
import json,sys
p=json.load(sys.stdin).get("public_check_engine",{})
sys.exit(0 if not p.get("errors") else 1)
'; then
    log_ok "Public check-engine reachable"
  fi
fi

while IFS= read -r warn; do
  [[ -n "$warn" ]] && log_warn "$warn"
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

# Ollama has no built-in auth — must not listen on 0.0.0.0 (Tenable CRITICAL).
if [[ "$HTTP_ONLY" != "1" ]] && command -v ssh >/dev/null 2>&1; then
  ollama_bind="$(ssh_remote "ss -tulpn 2>/dev/null | grep ':11434 ' || true")" || ollama_bind=""
  if echo "$ollama_bind" | grep -qE '0\.0\.0\.0:11434|\[::\]:11434'; then
    log_fail "Ollama listening on all interfaces — set OLLAMA_HOST=127.0.0.1:11434 (see docs/security/tenable-remediation.md)"
  elif echo "$ollama_bind" | grep -q '127.0.0.1:11434'; then
    log_ok "Ollama bound to loopback only"
  elif [[ -n "$ollama_bind" ]]; then
    log_warn "Ollama port 11434 bind: ${ollama_bind} — verify not reachable from OT LAN"
  fi
fi

if [[ -n "$LOGIN_USER" && -n "$LOGIN_PASS" ]]; then
  if echo "$probe_json" | python3 -c 'import json,sys; d=json.load(sys.stdin).get("login",{}); sys.exit(0 if d.get("login_status")==200 and not d.get("errors") else 1)'; then
    log_ok "Auth POST /api/auth/login for user ${LOGIN_USER}"
  fi
else
  log_ok "Auth login skipped (no credentials in ${AUTH_ENV})"
fi

if [[ "$HTTP_ONLY" == "1" ]]; then
  log_ok "SSH/docker checks skipped (--http-only)"
elif [[ "$INVENTORY_DOCKER_STACK" == "1" ]]; then
  log_ok "systemd units skipped (openfdd_docker_stack=true — health via /health/stack)"
  if command -v ssh >/dev/null 2>&1; then
    legacy_poll="$(ssh_remote "systemctl is-active openfdd-bacnet-poll 2>/dev/null || true")" || legacy_poll=""
    if [[ "$legacy_poll" == "active" ]]; then
      log_warn "Legacy openfdd-bacnet-poll systemd unit is active while Docker commission runs — disable it to avoid double BACnet polling"
    fi
    if feather_b="$(ssh_remote "du -sb ~/open-fdd/workspace/data/feather_store 2>/dev/null | awk '{print \$1}' || echo 0")"; then
      log_ok "Feather store on edge: ${feather_b:-0} bytes"
    else
      log_warn "Feather store check skipped (SSH to ${SSH_USER}@${HOST} failed — set SSHPASS in secrets/acme.env.local)"
    fi
    for svc in bridge commission mcp-rag; do
      if ! cid="$(ssh_remote "docker ps -q -f name=${svc} 2>/dev/null | head -1")"; then
        log_warn "Docker ${svc}: SSH unavailable (skipped log scan)"
        break
      fi
      if [[ -z "$cid" ]]; then
        log_fail "Docker service ${svc}: no running container"
        continue
      fi
      err_lines="$(ssh_remote "docker logs --tail 80 \"${cid}\" 2>&1 | grep -Ei 'ERROR|Traceback|CRITICAL' | grep -v '404 Not Found' | grep -v 'unknown-property' | grep -v 'Connection reset by peer' | tail -5 || true")" || err_lines=""
      if [[ -n "$err_lines" ]]; then
        log_fail "Docker ${svc} (${cid:0:12}) log errors: ${err_lines}"
      else
        log_ok "Docker ${svc} logs clean (last 80 lines, cid ${cid:0:12})"
      fi
    done
  fi
elif command -v ssh >/dev/null 2>&1; then
  for unit in caddy openfdd-bridge openfdd-bacnet-commission openfdd-mcp-rag; do
    if state="$(ssh_remote "systemctl is-active ${unit}")"; then
      [[ "$state" == "active" ]] && log_ok "systemd ${unit} active" || log_fail "systemd ${unit} state=${state}"
    else
      log_warn "systemd ${unit} check skipped (SSH failed)"
      break
    fi
  done
  if ssh_remote "grep -q reverse_proxy /etc/caddy/Caddyfile" >/dev/null 2>&1; then
    log_ok "Caddyfile reverse_proxy → bridge"
  elif ssh_remote "true" >/dev/null 2>&1; then
    log_fail "Caddyfile missing reverse_proxy (default Caddy page likely)"
  fi
  if mcp_loop="$(ssh_remote "curl -fsS http://127.0.0.1:8090/health 2>/dev/null || true")"; then
    if echo "$mcp_loop" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); sys.exit(0 if d.get("ok") else 1)' 2>/dev/null; then
      log_ok "MCP RAG loopback :8090/health OK"
    else
      log_fail "MCP RAG loopback :8090 not healthy"
    fi
  else
    log_warn "MCP loopback check skipped (SSH failed)"
  fi
fi

echo "---"
if [[ "$FAILURES" -gt 0 ]]; then
  echo "Post-deploy check FAILED (${FAILURES} issue(s))" >&2
  exit 1
fi
echo "Post-deploy check PASSED for ${HOST}"
exit 0
