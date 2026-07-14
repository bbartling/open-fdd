#!/usr/bin/env bash
# BACnet PCAP validation gate — fails CI if captured traffic violates expected patterns.
#
# Usage:
#   scripts/pcap_validate.sh [pcap_file]
#
# Env:
#   PCAP_FILE          — default capture path
#   PCAP_MIN_IAM       — minimum I-Am responses (default 0)
#   PCAP_MIN_WHOIS     — minimum Who-Is requests (default 0)
#   PCAP_MIN_READ      — minimum ReadProperty (default 0)
#   PCAP_MIN_RPM       — minimum ReadPropertyMultiple (default 0)
#   PCAP_MIN_WRITE     — minimum WriteProperty (default 0)
#   PCAP_FORBID_WRITE  — if 1, fail on any WriteProperty (default 0)
#   PCAP_DEVICE_ID     — optional BACnet device instance filter

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PCAP="${1:-${PCAP_FILE:-${ROOT}/artifacts/bacnet_capture.pcap}}"

if [[ ! -f "$PCAP" ]]; then
  echo "pcap_validate: skip — no capture at $PCAP"
  exit 0
fi

if ! command -v tshark >/dev/null 2>&1; then
  FRAMES=$(tcpdump -r "$PCAP" -nn udp port "${PCAP_UDP_PORT:-47808}" 2>/dev/null | wc -l | tr -d ' ')
  echo "pcap_validate: tshark not installed; udp frames=$FRAMES (APDU checks skipped)"
  exit 0
fi

DEVICE_FILTER=""
if [[ -n "${PCAP_DEVICE_ID:-}" ]]; then
  DEVICE_FILTER="bacnet.instance_number == ${PCAP_DEVICE_ID}"
fi

count_frames() {
  local display_filter="$1"
  local filter="$display_filter"
  if [[ -n "$DEVICE_FILTER" ]]; then
    filter="($display_filter) && ($DEVICE_FILTER)"
  fi
  tshark -r "$PCAP" -Y "$filter" -T fields -e frame.number 2>/dev/null | wc -l | tr -d ' '
}

IAM_COUNT=$(count_frames "bacapp.unconfirmed_service == 0")
WHOIS_COUNT=$(count_frames "bacapp.unconfirmed_service == 8")
READ_COUNT=$(count_frames "bacapp.confirmed_service == 12")
RPM_COUNT=$(count_frames "bacapp.confirmed_service == 14")
WRITE_COUNT=$(count_frames "bacapp.confirmed_service == 15")

MIN_IAM="${PCAP_MIN_IAM:-0}"
MIN_WHOIS="${PCAP_MIN_WHOIS:-0}"
MIN_READ="${PCAP_MIN_READ:-0}"
MIN_RPM="${PCAP_MIN_RPM:-0}"
MIN_WRITE="${PCAP_MIN_WRITE:-0}"
FORBID_WRITE="${PCAP_FORBID_WRITE:-0}"

echo "pcap_validate: file=$PCAP iam=$IAM_COUNT whois=$WHOIS_COUNT read=$READ_COUNT rpm=$RPM_COUNT writes=$WRITE_COUNT"

fail=0
if (( IAM_COUNT < MIN_IAM )); then
  echo "pcap_validate: FAIL — expected at least $MIN_IAM I-Am, got $IAM_COUNT"
  fail=1
fi
if (( WHOIS_COUNT < MIN_WHOIS )); then
  echo "pcap_validate: FAIL — expected at least $MIN_WHOIS Who-Is, got $WHOIS_COUNT"
  fail=1
fi
if (( READ_COUNT < MIN_READ )); then
  echo "pcap_validate: FAIL — expected at least $MIN_READ ReadProperty, got $READ_COUNT"
  fail=1
fi
if (( RPM_COUNT < MIN_RPM )); then
  echo "pcap_validate: FAIL — expected at least $MIN_RPM RPM, got $RPM_COUNT"
  fail=1
fi
if (( WRITE_COUNT < MIN_WRITE )); then
  echo "pcap_validate: FAIL — expected at least $MIN_WRITE WriteProperty, got $WRITE_COUNT"
  fail=1
fi
if (( FORBID_WRITE == 1 && WRITE_COUNT > 0 )); then
  echo "pcap_validate: FAIL — WriteProperty detected ($WRITE_COUNT) but PCAP_FORBID_WRITE=1"
  fail=1
fi

if (( fail )); then
  exit 1
fi

echo "pcap_validate: OK"
exit 0
