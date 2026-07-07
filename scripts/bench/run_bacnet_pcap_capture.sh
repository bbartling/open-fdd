#!/usr/bin/env bash
# Bench-only: capture BACnet/IP traffic during Open-FDD soak for PCAP regression vs vibe16 baseline.
set -euo pipefail

ROOT="${OPENFDD_COMPOSE_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
DURATION="${1:-300}"
IFACE="${OPENFDD_BACNET_PCAP_IFACE:-eth0}"
SHA="${OPENFDD_EDGE_SHA:-unknown}"
OUT_DIR="$ROOT/workspace/logs/pcap"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$OUT_DIR/openfdd_${SHA}_${STAMP}.pcap"

mkdir -p "$OUT_DIR"

if ! command -v tcpdump >/dev/null 2>&1; then
  echo "tcpdump required on bench host" >&2
  exit 1
fi

echo "Capturing BACnet/IP on $IFACE for ${DURATION}s → $OUT"
sudo tcpdump -i "$IFACE" -w "$OUT" 'udp port 47808' &
TPID=$!
sleep "$DURATION"
sudo kill "$TPID" 2>/dev/null || true
wait "$TPID" 2>/dev/null || true
echo "Wrote $OUT"
echo "Compare with vibe16 baseline via analyze_bacnet_pcap.py (see workspace/reports/BACNET_PCAP_* docs)"
