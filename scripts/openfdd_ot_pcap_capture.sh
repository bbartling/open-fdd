#!/usr/bin/env bash
# Capture OT traffic (BACnet, Modbus, bridge API, Haystack) without host sudo — uses Docker netshoot.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DURATION="${OPENFDD_PCAP_DURATION_SEC:-600}"
IFACE="${OPENFDD_PCAP_IFACE:-enp3s0}"
OT_HOST="${OPENFDD_PCAP_OT_HOST:-192.168.204.200}"
BENCH_IP="${OPENFDD_PCAP_BENCH_IP:-192.168.204.55}"
CONTAINER="${OPENFDD_PCAP_CONTAINER:-ofdd-pcap-capture}"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
PCAP_DIR="${OPENFDD_PCAP_DIR:-$ROOT/workspace/logs/pcap_${DURATION}s_${RUN_TS}}"
PCAP_FILE="$PCAP_DIR/openfdd_ot.pcap"
FILTER="${OPENFDD_PCAP_FILTER:-(udp port 47808 or tcp port 1502 or tcp port 8080 or tcp port 9091 or tcp port 443 or tcp port 502) and not port 22 and not port 53}"

mkdir -p "$PCAP_DIR"
echo "$PCAP_DIR" >"$ROOT/workspace/logs/pcap_latest.dir"

docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

log "Starting ${DURATION}s capture on $IFACE → $PCAP_FILE"
docker run -d --name "$CONTAINER" --net=host --cap-add=NET_ADMIN --cap-add=NET_RAW \
  -v "$PCAP_DIR:/pcap" \
  nicolaka/netshoot \
  timeout "$DURATION" tcpdump -i any -w /pcap/openfdd_ot.pcap -s 65535 "$FILTER" \
  >"$PCAP_DIR/docker.log" 2>&1

echo "$CONTAINER" >"$PCAP_DIR/container.name"
log "Container $CONTAINER started; filter: $FILTER"
