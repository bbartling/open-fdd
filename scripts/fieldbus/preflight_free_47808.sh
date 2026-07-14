#!/usr/bin/env bash
# Free UDP :47808 before starting the gateway BACnet server.
set -euo pipefail

echo "=== preflight: free BACnet UDP :47808 ==="

# Release any process currently holding 47808/udp so the server can bind.
if command -v fuser >/dev/null 2>&1; then
  if fuser 47808/udp 2>/dev/null; then
    echo "Releasing 47808/udp via fuser -k"
    fuser -k 47808/udp 2>/dev/null || true
    sleep 1
  fi
fi

if ss -lun 2>/dev/null | grep -q ':47808'; then
  echo "WARNING: something still bound to :47808"
  ss -lun | grep 47808 || true
else
  echo "OK: UDP :47808 is free"
fi
