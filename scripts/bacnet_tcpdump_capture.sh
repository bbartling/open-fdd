#!/usr/bin/env bash
# Host-side BACnet/IP packet capture for edge diagnostics (not inside bridge container).
#
#   sudo ./scripts/bacnet_tcpdump_capture.sh --interface eth0
#   sudo ./scripts/bacnet_tcpdump_capture.sh --interface eth0 --minutes 5 --compress
#   sudo ./scripts/bacnet_tcpdump_capture.sh --interface eth0 --scp user@host:/path/
#
# SECURITY: captures BACnet traffic on the LAN — may include building control data.
# Store captures securely; do not commit pcaps to git.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MINUTES=20
IFACE=""
HOST_IP=""
PORT=47808
OUT_DIR="/tmp/openfdd-captures"
SCP_DEST=""
COMPRESS=0
DRY_RUN=0

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --minutes) MINUTES="${2:?}"; shift 2 ;;
    --interface) IFACE="${2:?}"; shift 2 ;;
    --host-ip) HOST_IP="${2:?}"; shift 2 ;;
    --port) PORT="${2:?}"; shift 2 ;;
    --out-dir) OUT_DIR="${2:?}"; shift 2 ;;
    --scp) SCP_DEST="${2:?}"; shift 2 ;;
    --compress) COMPRESS=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$IFACE" ]]; then
  echo "ERROR: --interface is required (e.g. eth0)" >&2
  exit 1
fi

if [[ "$DRY_RUN" != 1 ]]; then
  if ! command -v tcpdump >/dev/null 2>&1; then
    echo "ERROR: tcpdump not found. Install: sudo apt-get install -y tcpdump" >&2
    exit 1
  fi
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: run as root or with sudo for packet capture" >&2
    exit 1
  fi
fi

mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
BASE="openfdd-bacnet-${STAMP}-${IFACE}-${MINUTES}m.pcap"
OUT_PATH="${OUT_DIR}/${BASE}"

if [[ -e "$OUT_PATH" ]]; then
  echo "ERROR: output exists (refusing to overwrite): $OUT_PATH" >&2
  exit 1
fi

FILTER="udp port ${PORT}"
if [[ -n "$HOST_IP" ]]; then
  FILTER="host ${HOST_IP} and ${FILTER}"
fi

SECONDS=$((MINUTES * 60))
echo "==> BACnet tcpdump capture"
echo "    interface: $IFACE"
echo "    duration:  ${MINUTES}m (${SECONDS}s)"
echo "    filter:    $FILTER"
echo "    output:    $OUT_PATH"

if [[ "$DRY_RUN" == 1 ]]; then
  echo "DRY-RUN: would run: timeout ${SECONDS}s tcpdump -i ${IFACE} -w ${OUT_PATH} ${FILTER}"
  exit 0
fi

timeout "${SECONDS}s" tcpdump -i "$IFACE" -w "$OUT_PATH" $FILTER
echo "==> Capture saved: $OUT_PATH ($(du -h "$OUT_PATH" | awk '{print $1}'))"

FINAL_PATH="$OUT_PATH"
if [[ "$COMPRESS" == 1 ]]; then
  gzip -9 "$OUT_PATH"
  FINAL_PATH="${OUT_PATH}.gz"
  echo "==> Compressed: $FINAL_PATH"
fi

if [[ -n "$SCP_DEST" ]]; then
  if ! command -v scp >/dev/null 2>&1; then
    echo "ERROR: scp not found" >&2
    exit 1
  fi
  echo "==> SCP to $SCP_DEST"
  scp "$FINAL_PATH" "$SCP_DEST"
fi

echo "Done."
