#!/usr/bin/env bash
# Docker compose health audit — unhealthy containers, restart loops, error log scan.
#
#   ./scripts/openfdd_docker_health_audit.sh
#   OPENFDD_DOCKER_HEALTH_DIR=... ./scripts/openfdd_docker_health_audit.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"

openfdd_bench_load_profile "$ROOT" || true

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${OPENFDD_DOCKER_HEALTH_DIR:-$ROOT/workspace/logs/docker_health_${RUN_TS}}"
FAIL=0
pass=0
fail=0
skip=0

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/audit.log") 2>&1

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }
check() {
  local name="$1" ok="$2" detail="$3"
  openfdd_bench_check_line "$name" "$ok" "$detail" "$LOG_DIR/summary.txt"
  if [[ "$ok" == "pass" ]]; then pass=$((pass + 1))
  elif [[ "$ok" == "skip" ]]; then skip=$((skip + 1))
  else fail=$((fail + 1)); FAIL=1; fi
}

: >"$LOG_DIR/summary.txt"
log "=== Docker health audit → $LOG_DIR ==="
log "profile=${OPENFDD_BENCH_PROFILE:-none}"

COMPOSE="$(openfdd_rust_resolve_compose_file "$ROOT")"
if [[ -z "$COMPOSE" || ! -f "$COMPOSE" ]]; then
  check "compose-file" fail "no docker-compose.yml found"
  exit 1
fi
check "compose-file" pass "$COMPOSE"

if ! openfdd_rust_check_docker 2>/dev/null; then
  check "docker-daemon" fail "docker not running"
  exit 1
fi
check "docker-daemon" pass "docker OK"

docker compose -f "$COMPOSE" ps | tee "$LOG_DIR/compose_ps.txt" || {
  check "compose-ps" fail "docker compose ps failed"
  exit 1
}
check "compose-ps" pass "compose ps captured"

# Running vs expected edge services
running="$(docker compose -f "$COMPOSE" ps --services --status running 2>/dev/null | sort | tr '\n' ' ')"
log "running services: ${running:-none}"
if [[ -z "${running// /}" ]]; then
  check "services-running" fail "no compose services running"
else
  check "services-running" pass "${running}"
fi

# Unhealthy healthchecks
unhealthy_json="$(docker compose -f "$COMPOSE" ps --format json 2>/dev/null | jq -rs '[.[] | select(.Health != null and .Health != "" and .Health != "healthy")]' || echo '[]')"
unhealthy_count="$(jq 'length' <<<"$unhealthy_json")"
echo "$unhealthy_json" >"$LOG_DIR/unhealthy.json"
if [[ "$unhealthy_count" -gt 0 ]]; then
  jq -r '.[] | "\(.Name // .Service): \(.Health)"' <<<"$unhealthy_json" | tee "$LOG_DIR/unhealthy.txt"
  check "healthcheck" fail "${unhealthy_count} container(s) not healthy (see unhealthy.txt)"
else
  check "healthcheck" pass "all healthchecks healthy or unset"
fi

# Restart storm detection
: >"$LOG_DIR/restart_counts.txt"
while read -r svc; do
  [[ -n "$svc" ]] || continue
  cid="$(docker compose -f "$COMPOSE" ps -q "$svc" 2>/dev/null | head -1)"
  [[ -n "$cid" ]] || continue
  cname="$(docker inspect --format '{{.Name}}' "$cid" 2>/dev/null | sed 's/^\///')"
  restarts="$(docker inspect --format '{{.RestartCount}}' "$cid" 2>/dev/null || echo 0)"
  echo "$cname restarts=$restarts" | tee -a "$LOG_DIR/restart_counts.txt"
  if [[ "${restarts:-0}" -gt 5 ]]; then
    check "restart-$svc" fail "$cname restart_count=$restarts (>5 — crash loop?)"
  fi
done < <(docker compose -f "$COMPOSE" ps --services 2>/dev/null)

# Log error scan
PATTERNS="${OPENFDD_WONKY_LOG_PATTERNS:-[\"panic\",\"fatal error\",\"FATAL\"]}"
: >"$LOG_DIR/log_errors.txt"
pattern_re="$(python3 -c 'import json,sys,re; p=json.loads(sys.argv[1]); print("|".join(p))' "$PATTERNS" 2>/dev/null || echo 'panic|fatal error|FATAL')"
since="${OPENFDD_DOCKER_LOG_SINCE:-24h}"
while read -r cname; do
  [[ -n "$cname" ]] || continue
  docker logs --since "$since" "$cname" 2>&1 \
    | grep -Ei "$pattern_re" \
    | tail -30 >>"$LOG_DIR/log_errors.txt" || true
done < <(docker compose -f "$COMPOSE" ps --services 2>/dev/null | while read -r svc; do
  docker compose -f "$COMPOSE" ps -q "$svc" 2>/dev/null | xargs -r docker inspect --format '{{.Name}}' 2>/dev/null | sed 's/^\///'
done)

if [[ -s "$LOG_DIR/log_errors.txt" ]]; then
  check "log-errors" fail "panic/fatal/error patterns in container logs (see log_errors.txt)"
else
  check "log-errors" pass "no panic/fatal patterns in last ${since} logs"
fi

# Bridge /api/health from host (matches compose healthcheck)
BRIDGE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
health="$(curl -fsS "${BRIDGE}/api/health" 2>/dev/null || echo '{}')"
echo "$health" >"$LOG_DIR/bridge_health.json"
if jq -e '.ok == true' <<<"$health" >/dev/null 2>&1; then
  check "bridge-health" pass "GET /api/health ok"
else
  check "bridge-health" fail "GET /api/health not ok"
fi

jq -nc \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg dir "$LOG_DIR" \
  --argjson pass "$pass" --argjson fail "$fail" --argjson skip "$skip" \
  '{timestamp_utc:$ts,artifact_dir:$dir,pass_count:$pass,fail_count:$fail,skip_count:$skip,ok:($fail==0)}' \
  >"$LOG_DIR/result.json"

echo | tee -a "$LOG_DIR/summary.txt"
echo "Result: pass=$pass fail=$fail skip=$skip artifact=$LOG_DIR" | tee -a "$LOG_DIR/summary.txt"
log "=== DONE fail=$fail ==="
[[ "$FAIL" -eq 0 ]]
