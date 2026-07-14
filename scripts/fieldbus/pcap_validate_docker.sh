#!/usr/bin/env bash
# Run pcap_validate.sh inside the gateway image (includes tshark).
#
# Usage: scripts/pcap_validate_docker.sh [pcap_file]
# Env: same as scripts/pcap_validate.sh plus PCAP_VALIDATE_IMAGE (default diy-bacnet-server:rust)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PCAP="${1:-${PCAP_FILE:-${ROOT}/artifacts/bacnet_capture.pcap}}"
IMAGE="${PCAP_VALIDATE_IMAGE:-diy-bacnet-server:rust}"

if [[ ! -f "$PCAP" ]]; then
  echo "pcap_validate_docker: skip — no capture at $PCAP"
  exit 0
fi

PCAP_ABS="$(realpath "$PCAP")"
PCAP_DIR="$(dirname "$PCAP_ABS")"
PCAP_BASE="$(basename "$PCAP_ABS")"

docker run --rm \
  -v "${PCAP_DIR}:/pcap:ro" \
  -v "${SCRIPT_DIR}/pcap_validate.sh:/app/scripts/pcap_validate.sh:ro" \
  -e PCAP_MIN_IAM="${PCAP_MIN_IAM:-0}" \
  -e PCAP_MIN_WHOIS="${PCAP_MIN_WHOIS:-0}" \
  -e PCAP_MIN_READ="${PCAP_MIN_READ:-0}" \
  -e PCAP_MIN_RPM="${PCAP_MIN_RPM:-0}" \
  -e PCAP_MIN_WRITE="${PCAP_MIN_WRITE:-0}" \
  -e PCAP_FORBID_WRITE="${PCAP_FORBID_WRITE:-0}" \
  -e PCAP_DEVICE_ID="${PCAP_DEVICE_ID:-}" \
  --entrypoint /app/scripts/pcap_validate.sh \
  "$IMAGE" "/pcap/${PCAP_BASE}"
