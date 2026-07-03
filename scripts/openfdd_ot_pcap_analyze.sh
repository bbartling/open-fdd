#!/usr/bin/env bash
# Dissect OT pcap — protocol summary, BACnet BVLC/NPDU, Modbus, HTTP (no host tshark required).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PCAP_DIR="${1:-$(cat "$ROOT/workspace/logs/pcap_latest.dir" 2>/dev/null || true)}"
PCAP="${PCAP_DIR}/openfdd_ot.pcap"
OUT="${PCAP_DIR}/analysis.txt"

if [[ ! -f "$PCAP" ]]; then
  echo "ERROR: missing $PCAP" >&2
  exit 1
fi

SIZE="$(wc -c <"$PCAP" | tr -d ' ')"
{
  echo "=== Open-FDD OT PCAP analysis ==="
  echo "File: $PCAP"
  echo "Size: ${SIZE} bytes"
  echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
} >"$OUT"

docker run --rm -v "$PCAP_DIR:/pcap:ro" nicolaka/netshoot sh -c '
  PCAP=/pcap/openfdd_ot.pcap
  echo "=== Packet count ==="
  tcpdump -r "$PCAP" 2>/dev/null | wc -l
  echo
  echo "=== Protocol / port summary (tcpdump) ==="
  tcpdump -r "$PCAP" -n 2>/dev/null | awk "
    /UDP/ && /47808/ {bacnet++}
    /UDP/ && /47808/ && /192.168.204.200/ {bacnet_dev++}
    /UDP/ && /47808/ && /192.168.204.55/ {bacnet_bench++}
    /TCP/ && /\.1502/ {modbus++}
    /TCP/ && /\.8080/ {http8080++}
    /TCP/ && /\.9092/ {haystack++}
    /Who-Is|I-Am|ReadProperty|WriteProperty|BVLC|NPDU/ {bacnet_named++}
    {total++}
    END {
      print \"total_lines\", total+0
      print \"bacnet_udp_47808\", bacnet+0
      print \"bacnet_from_to_200\", bacnet_dev+0
      print \"bacnet_from_to_55\", bacnet_bench+0
      print \"modbus_tcp_1502\", modbus+0
      print \"http_bridge_8080\", http8080+0
      print \"haystack_9092\", haystack++0
      print \"bacnet_keyword_hits\", bacnet_named+0
    }"
  echo
  echo "=== Top talkers (IP pairs, first 20) ==="
  tcpdump -r "$PCAP" -n 2>/dev/null | awk "{print \$3,\$5}" | sed "s/:$//" | sort | uniq -c | sort -rn | head -20
  echo
  echo "=== BACnet UDP sample (up to 30 packets) ==="
  tcpdump -r "$PCAP" -n "udp port 47808" 2>/dev/null | head -30
  echo
  echo "=== Modbus TCP sample (up to 15) ==="
  tcpdump -r "$PCAP" -n "tcp port 1502" 2>/dev/null | head -15
  echo
  echo "=== Bridge HTTP :8080 sample (up to 15) ==="
  tcpdump -r "$PCAP" -n "tcp port 8080" 2>/dev/null | head -15
  echo
  echo "=== BACnet frame hex (first 5 UDP 47808, 64 bytes payload) ==="
  tcpdump -r "$PCAP" -n -X "udp port 47808 and host 192.168.204.200" 2>/dev/null | head -80
' >>"$OUT" 2>&1

# Optional deeper BACnet BVLC parse if tshark available in image
if docker run --rm nicolaka/netshoot which tshark >/dev/null 2>&1; then
  docker run --rm -v "$PCAP_DIR:/pcap:ro" nicolaka/netshoot sh -c '
    echo "=== tshark BACnet summary ==="
    tshark -r /pcap/openfdd_ot.pcap -Y bacnet -T fields -e frame.number -e ip.src -e ip.dst -e bacnet.type -e bacnet.service_choice 2>/dev/null | head -40
  ' >>"$OUT" 2>&1 || true
fi

echo "Analysis written: $OUT"
cat "$OUT"
