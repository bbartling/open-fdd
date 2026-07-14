#!/usr/bin/env bash
# Shared bench defaults for diy-bacnet-server — modeled on open-fdd/scripts smoke profiles.
#
# Sidecar startup (docker/.env): OPENFDD_FIELDBUS_BIND, API key, HAYSTACK_* for Niagara.
# Per-request targets (Modbus host/port, BACnet device/point): exported here and passed in JSON bodies.
#
# Override via environment or copy scripts/bench.env.example → scripts/bench.env.local
bench_load_env() {
  local root="${1:?root}"
  if [[ -f "$root/scripts/bench.env.local" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$root/scripts/bench.env.local"
    set +a
  fi
}

# ---- HTTP / auth (sidecar) ----
export BENCH_BASE="${BENCH_BASE:-${SMOKE_BASE:-http://127.0.0.1:8080}}"
export OPENFDD_FIELDBUS_API_KEY="${OPENFDD_FIELDBUS_API_KEY:-${RUSTY_GATEWAY_API_KEY:-}}"

# ---- BACnet client (POST body fields) ----
export BENCH_BACNET_DEVICE="${BENCH_BACNET_DEVICE:-${SMOKE_DEVICE:-5007}}"
export BENCH_BACNET_READ_TYPE="${BENCH_BACNET_READ_TYPE:-${SMOKE_READ_TYPE:-analog-input}}"
export BENCH_BACNET_READ_INST="${BENCH_BACNET_READ_INST:-${SMOKE_READ_INST:-1173}}"
export BENCH_BACNET_OVR_TYPE="${BENCH_BACNET_OVR_TYPE:-${SMOKE_OVERRIDE_TYPE:-analog-output}}"
export BENCH_BACNET_OVR_INST="${BENCH_BACNET_OVR_INST:-${SMOKE_OVERRIDE_INST:-2466}}"
export BENCH_BACNET_EXPECT_PRIORITY="${BENCH_BACNET_EXPECT_PRIORITY:-${SMOKE_OVERRIDE_PRIORITY:-8}}"
export BENCH_BACNET_EXPECT_VALUE="${BENCH_BACNET_EXPECT_VALUE:-${SMOKE_OVERRIDE_VALUE:-55}}"
export BENCH_BACNET_WRITE_PRIORITY="${BENCH_BACNET_WRITE_PRIORITY:-${SMOKE_WRITE_PRIORITY:-10}}"
export BENCH_HOSTED_INSTANCE="${BENCH_HOSTED_INSTANCE:-${SMOKE_HOSTED_INSTANCE:-599999}}"
export BENCH_BACNET_UDP_PORT="${BENCH_BACNET_UDP_PORT:-47808}"
export BENCH_PCAP_FILTER="${BENCH_PCAP_FILTER:-udp port ${BENCH_BACNET_UDP_PORT}}"

# ---- Modbus (POST /modbus/read body — not sidecar .env) ----
export BENCH_MODBUS_HOST="${BENCH_MODBUS_HOST:-192.168.204.14}"
export BENCH_MODBUS_PORT="${BENCH_MODBUS_PORT:-1502}"
export BENCH_MODBUS_UNIT="${BENCH_MODBUS_UNIT:-1}"
export BENCH_MODBUS_REG="${BENCH_MODBUS_REG:-0}"
export BENCH_MODBUS_FN="${BENCH_MODBUS_FN:-input}"

# ---- Haystack (gateway startup env — sidecar must be started with HAYSTACK_*) ----
export BENCH_HAYSTACK_URL="${BENCH_HAYSTACK_URL:-https://192.168.204.11/haystack}"
export BENCH_HAYSTACK_USER="${BENCH_HAYSTACK_USER:-open_fdd}"
export BENCH_HAYSTACK_FILTER="${BENCH_HAYSTACK_FILTER:-point and temp}"
export BENCH_HAYSTACK_HIS_ID="${BENCH_HAYSTACK_HIS_ID:-}"

# ---- timing ----
export BENCH_TIMEOUT="${BENCH_TIMEOUT:-${SMOKE_TIMEOUT:-45}}"
export BENCH_SUP_TIMEOUT="${BENCH_SUP_TIMEOUT:-${SMOKE_SUP_TIMEOUT:-240}}"

bench_require_tools() {
  command -v jq >/dev/null || { echo "FATAL: jq required" >&2; exit 2; }
  command -v curl >/dev/null || { echo "FATAL: curl required" >&2; exit 2; }
}

bench_auth_args() {
  BENCH_AUTH=()
  [[ -n "${OPENFDD_FIELDBUS_API_KEY:-}" ]] && BENCH_AUTH=(-H "Authorization: Bearer ${OPENFDD_FIELDBUS_API_KEY}")
}

bench_api() {
  curl -fsS --max-time "$BENCH_TIMEOUT" -H 'Content-Type: application/json' "${BENCH_AUTH[@]}" "$@"
}

bench_apis() {
  curl -fsS --max-time "$BENCH_SUP_TIMEOUT" -H 'Content-Type: application/json' "${BENCH_AUTH[@]}" "$@"
}

bench_approx() {
  awk -v a="$1" -v b="$2" 'BEGIN{d=a-b; if(d<0)d=-d; exit !(d<=1.0)}'
}

# Start background PCAP capture to $1 for $2 seconds; echoes docker container id or tcpdump PID.
bench_capture_start() {
  local out="$1" secs="$2"
  local dir file
  dir="$(dirname "$out")"
  file="$(basename "$out")"
  mkdir -p "$dir"
  rm -f "$out"

  if command -v docker >/dev/null 2>&1; then
    local cname="bench-pcap-${RANDOM:-0}-$$"
    docker run -d --rm --name "$cname" --net=host --cap-add=NET_RAW \
      -v "${dir}:/pcap" nicolaka/netshoot \
      timeout "$secs" tcpdump -i any -nn -s 0 "$BENCH_PCAP_FILTER" -w "/pcap/${file}" 2>/dev/null
    echo "$cname"
    return
  fi
  if sudo -n true 2>/dev/null; then
    sudo timeout "$secs" tcpdump -i any -nn -s 0 "$BENCH_PCAP_FILTER" -w "$out" 2>/dev/null &
    echo $!
    return
  fi
  echo ""
}

bench_capture_stop() {
  local id="$1"
  [[ -z "$id" ]] && return
  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$id"; then
    docker stop "$id" >/dev/null 2>&1 || true
    docker wait "$id" >/dev/null 2>&1 || true
    return
  fi
  if docker ps -q --filter "id=$id" 2>/dev/null | grep -q .; then
    docker stop "$id" >/dev/null 2>&1 || true
    docker wait "$id" >/dev/null 2>&1 || true
    return
  fi
  kill "$id" 2>/dev/null || true
  wait "$id" 2>/dev/null || true
}

bench_capture_wait() {
  bench_capture_stop "$1"
}

bench_pcap_frames() {
  local pcap="$1" filter="${2:-${BENCH_PCAP_FILTER}}"
  if [[ ! -s "$pcap" ]]; then
    echo 0
    return
  fi
  if [[ -n "${2:-}" ]]; then
    if command -v tshark >/dev/null 2>&1; then
      tshark -r "$pcap" -Y "$2" -T fields -e frame.number 2>/dev/null | wc -l | tr -d ' '
      return
    fi
    if command -v docker >/dev/null 2>&1; then
      local dir base
      dir="$(dirname "$(realpath "$pcap")")"
      base="$(basename "$pcap")"
      docker run --rm -v "${dir}:/pcap:ro" --entrypoint tshark "${PCAP_VALIDATE_IMAGE:-diy-bacnet-server:rust}" \
        -r "/pcap/${base}" -Y "$2" -T fields -e frame.number 2>/dev/null | wc -l | tr -d ' '
      return
    fi
  fi
  tcpdump -r "$pcap" -nn "$filter" 2>/dev/null | wc -l | tr -d ' '
}

# tshark display filters for BACnet client phases (Wireshark bacapp dissector).
bench_pcap_filter_whois() { echo 'bacapp.unconfirmed_service == 8'; }
bench_pcap_filter_iam()    { echo 'bacapp.unconfirmed_service == 0'; }
bench_pcap_filter_read()   { echo 'bacapp.confirmed_service == 12'; }
bench_pcap_filter_rpm()    { echo 'bacapp.confirmed_service == 14'; }
bench_pcap_filter_write()  { echo 'bacapp.confirmed_service == 15'; }

bench_modbus_body() {
  jq -nc \
    --arg host "$BENCH_MODBUS_HOST" \
    --argjson port "$BENCH_MODBUS_PORT" \
    --argjson unit "$BENCH_MODBUS_UNIT" \
    --argjson addr "$BENCH_MODBUS_REG" \
    --arg fn "$BENCH_MODBUS_FN" \
    '{host:$host,port:$port,unit_id:$unit,timeout:5.0,registers:[{address:$addr,count:1,function:$fn,decode:"uint16",label:"bench"}]}'
}
