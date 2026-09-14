#!/usr/bin/env bash
# Local Mint/OptiPlex BACnet OT + Open-FDD MQTTS pipeline smoke.
#
# Modes:
#   whois     — BACpypes3 Who-Is on the OT NIC (default 192.168.204.11/24)
#   read      — unicast ReadProperty (requires READ_TARGET or --target via env)
#   sensor    — Who-Is + ReadProperty + numeric/range check (preferred LAN proof)
#   pipeline  — Containerized bacpypes3-sim → fieldbus → mqtt → central (GHCR sha-*)
#   all       — whois + sensor + pipeline (default)
#
# Examples:
#   ./scripts/ops/local_bacnet_ot_bench.sh
#   ./scripts/ops/local_bacnet_ot_bench.sh sensor
#   READ_TARGET=192.168.204.55 READ_OBJECT=analog-value,1 \
#     ./scripts/ops/local_bacnet_ot_bench.sh read
#   OPENFDD_IMAGE_TAG=sha-9072e0b ./scripts/ops/local_bacnet_ot_bench.sh pipeline
#   BIND=192.168.204.11/24 ./scripts/ops/local_bacnet_ot_bench.sh whois
#
# Docs: docs/operations/LOCAL_BACNET_BACPYPE3_BENCH.md
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

MODE="${1:-all}"
BIND="${OPENFDD_BACNET_BIND:-${BIND:-192.168.204.11/24}}"
TAG="${OPENFDD_IMAGE_TAG:-}"
VENV="${OPENFDD_BACPYPE3_VENV:-$ROOT/.venv-bacpypes3}"
ART="${ARTIFACT_DIR:-$ROOT/reports/local_bacnet_ot_$(date -u +%Y%m%dT%H%M%SZ)}"
# Peer IPs change on the bench — override when DHCP moves the sim/device.
READ_TARGET="${READ_TARGET:-${OPENFDD_BACNET_READ_TARGET:-}}"
READ_OBJECT="${READ_OBJECT:-${OPENFDD_BACNET_READ_OBJECT:-analog-value,1}}"
READ_PROPERTY="${READ_PROPERTY:-present-value}"
EXPECT_MIN="${EXPECT_MIN:-}"
EXPECT_MAX="${EXPECT_MAX:-}"
mkdir -p "$ART"

log() { printf '[local-bacnet-ot] %s\n' "$*"; }

ensure_venv() {
  if [[ -x "$VENV/bin/python" ]]; then
    "$VENV/bin/python" -c 'import bacpypes3, ifaddr' 2>/dev/null && return 0
  fi
  command -v uv >/dev/null || {
    log "installing uv (user)…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="${HOME}/.local/bin:${PATH}"
  }
  log "creating $VENV with bacpypes3 + ifaddr…"
  uv venv "$VENV"
  uv pip install --python "$VENV/bin/python" bacpypes3 ifaddr
}

run_whois() {
  ensure_venv
  log "BACpypes3 Who-Is bind=$BIND"
  set +e
  "$VENV/bin/python" "$ROOT/scripts/ops/bacpypes3_whois_smoke.py" whois \
    --address "$BIND" \
    --timeout "${WHOIS_TIMEOUT:-8}" \
    --min-devices "${WHOIS_MIN_DEVICES:-1}" \
    --json | tee "$ART/whois.json"
  local rc=${PIPESTATUS[0]}
  set -e
  if [[ "$rc" -ne 0 ]]; then
    log "WARN: Who-Is found no devices (LAN quiet or wrong NIC). Pipeline mode still valid."
    echo '{"ok":false,"warn":"no_iam"}' >"$ART/whois_verdict.json"
    return 0
  fi
  echo '{"ok":true}' >"$ART/whois_verdict.json"
  log "Who-Is PASS → $ART/whois.json"
}

run_read() {
  ensure_venv
  local target="$READ_TARGET"
  if [[ -z "$target" ]]; then
    log "ERROR: set READ_TARGET=192.168.204.x (peer IPs change on the bench)"
    echo '{"ok":false,"error":"READ_TARGET required"}' >"$ART/read_verdict.json"
    return 1
  fi
  log "BACpypes3 ReadProperty target=$target object=$READ_OBJECT prop=$READ_PROPERTY"
  set +e
  "$VENV/bin/python" "$ROOT/scripts/ops/bacpypes3_whois_smoke.py" read \
    --address "$BIND" \
    --target "$target" \
    --object "$READ_OBJECT" \
    --property "$READ_PROPERTY" \
    --timeout "${READ_TIMEOUT:-5}" \
    --json | tee "$ART/read.json"
  local rc=${PIPESTATUS[0]}
  set -e
  echo "{\"ok\": $([[ $rc -eq 0 ]] && echo true || echo false)}" >"$ART/read_verdict.json"
  [[ "$rc" -eq 0 ]] || { log "ReadProperty FAIL"; return "$rc"; }
  log "ReadProperty PASS → $ART/read.json"
}

run_sensor() {
  ensure_venv
  local extra=()
  [[ -n "$READ_TARGET" ]] && extra+=(--target "$READ_TARGET")
  [[ -n "$EXPECT_MIN" ]] && extra+=(--expect-min "$EXPECT_MIN")
  [[ -n "$EXPECT_MAX" ]] && extra+=(--expect-max "$EXPECT_MAX")
  log "BACpypes3 sensor smoke bind=$BIND target=${READ_TARGET:-auto} object=$READ_OBJECT"
  set +e
  "$VENV/bin/python" "$ROOT/scripts/ops/bacpypes3_whois_smoke.py" sensor \
    --address "$BIND" \
    --object "$READ_OBJECT" \
    --property "$READ_PROPERTY" \
    --whois-timeout "${WHOIS_TIMEOUT:-8}" \
    --read-timeout "${READ_TIMEOUT:-5}" \
    --min-devices "${WHOIS_MIN_DEVICES:-1}" \
    "${extra[@]}" \
    --json | tee "$ART/sensor.json"
  local rc=${PIPESTATUS[0]}
  set -e
  # Keep whois artifact for all-mode summary when sensor ran first.
  if [[ -f "$ART/sensor.json" ]]; then
    cp "$ART/sensor.json" "$ART/whois.json" 2>/dev/null || true
  fi
  echo "{\"ok\": $([[ $rc -eq 0 ]] && echo true || echo false)}" >"$ART/sensor_verdict.json"
  echo "{\"ok\": $([[ $rc -eq 0 ]] && echo true || echo false)}" >"$ART/whois_verdict.json"
  [[ "$rc" -eq 0 ]] || { log "Sensor smoke FAIL (Who-Is and/or ReadProperty)"; return "$rc"; }
  log "Sensor smoke PASS → $ART/sensor.json"
}

resolve_tag() {
  if [[ -n "$TAG" ]]; then
    echo "$TAG"
    return
  fi
  if [[ -x "$ROOT/scripts/ghcr_newest_by_created.py" ]]; then
    local newest
    newest="$("$ROOT/scripts/ghcr_newest_by_created.py" openfdd-fieldbus 2>/dev/null | awk 'NR==1{print $2}')"
    if [[ "$newest" =~ ^sha-[0-9a-f]{7}$ ]]; then
      echo "$newest"
      return
    fi
  fi
  # Fallback: current Wave N/O ops pin family
  echo "sha-9072e0b"
}

run_pipeline() {
  command -v docker >/dev/null || { log "ERROR: docker required"; return 2; }
  docker info >/dev/null || { log "ERROR: docker daemon not reachable"; return 2; }
  export DOCKER_CONFIG="${DOCKER_CONFIG:-$HOME/.docker}"
  if ! docker compose version >/dev/null 2>&1; then
    log "ERROR: docker compose plugin missing. Install user plugin:"
    log "  mkdir -p ~/.docker/cli-plugins"
    log "  curl -fsSL https://github.com/docker/compose/releases/download/v2.40.3/docker-compose-linux-x86_64 -o ~/.docker/cli-plugins/docker-compose"
    log "  chmod +x ~/.docker/cli-plugins/docker-compose"
    return 2
  fi
  local tip
  tip="$(resolve_tag)"
  log "MQTTS pipeline smoke OPENFDD_IMAGE_TAG=$tip (containerized bacpypes3 sim)"
  OPENFDD_IMAGE_TAG="$tip" \
    bash "$ROOT/scripts/integration/bacnet_mqtt_container_smoke.sh" 2>&1 | tee "$ART/pipeline.log"
  local rc=${PIPESTATUS[0]}
  echo "{\"ok\": $([[ $rc -eq 0 ]] && echo true || echo false), \"tag\": \"$tip\"}" \
    >"$ART/pipeline_verdict.json"
  [[ "$rc" -eq 0 ]] || return "$rc"
  log "Pipeline PASS → $ART/pipeline.log"
}

case "$MODE" in
  whois) run_whois ;;
  read) run_read ;;
  sensor) run_sensor ;;
  pipeline) run_pipeline ;;
  all)
    # Who-Is alone is insufficient; sensor includes Who-Is + ReadProperty.
    run_sensor
    run_pipeline
    ;;
  *)
    echo "usage: $0 [whois|read|sensor|pipeline|all]" >&2
    exit 2
    ;;
esac

jq -n \
  --arg art "$ART" \
  --arg mode "$MODE" \
  --arg bind "$BIND" \
  --slurpfile whois <(test -f "$ART/whois_verdict.json" && cat "$ART/whois_verdict.json" || echo 'null') \
  --slurpfile sensor <(test -f "$ART/sensor_verdict.json" && cat "$ART/sensor_verdict.json" || echo 'null') \
  --slurpfile readv <(test -f "$ART/read_verdict.json" && cat "$ART/read_verdict.json" || echo 'null') \
  --slurpfile pipe <(test -f "$ART/pipeline_verdict.json" && cat "$ART/pipeline_verdict.json" || echo 'null') \
  '{ok:true, mode:$mode, bind:$bind, artifact:$art,
    whois: ($whois[0] // null), sensor: ($sensor[0] // null),
    read: ($readv[0] // null), pipeline: ($pipe[0] // null)}' \
  2>/dev/null | tee "$ART/summary.json" || true

log "done artifact=$ART"
exit 0
