#!/usr/bin/env bash
# Server-side LAN access check (run on bensserver).
set -euo pipefail
PORT="${1:-8765}"
LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
TS_IP="$(ip -4 addr show tailscale0 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 || true)"

echo "=== bensserver LAN firewall check (port $PORT) ==="
echo "LAN IP: ${LAN_IP:-unknown}"
[[ -n "$TS_IP" ]] && echo "Tailscale: $TS_IP"
echo ""

if ss -tlnp 2>/dev/null | grep -q ":${PORT} "; then
  echo "✓ uvicorn listening on 0.0.0.0:${PORT}"
else
  echo "✗ nothing listening on port $PORT — run: ./scripts/run_local.sh start"
  exit 1
fi

if curl -sf --connect-timeout 2 "http://127.0.0.1:${PORT}/health" >/dev/null; then
  echo "✓ localhost health OK"
else
  echo "✗ localhost health failed"
  exit 1
fi

UFW_ACTIVE=false
if systemctl is-active --quiet ufw 2>/dev/null; then
  UFW_ACTIVE=true
  echo ""
  echo "⚠ UFW is ACTIVE — remote LAN browsers will TIME OUT unless port $PORT is allowed."
  echo "  Fix (run once, needs sudo password):"
  echo "    sudo ./scripts/open_lan_port.sh $PORT"
  if command -v ufw >/dev/null 2>&1; then
    echo ""
    echo "  Current rules (needs sudo to list fully):"
    sudo ufw status numbered 2>/dev/null | grep -E "$PORT|Status|To " || true
  fi
fi

if ! $UFW_ACTIVE; then
  echo "✓ UFW not active (or not installed)"
fi

echo ""
echo "From Windows PC:"
echo "  powershell -ExecutionPolicy Bypass -File scripts\\lan_diag.ps1"
echo "Browser:"
echo "  http://${LAN_IP}:${PORT}/login"
[[ -n "$TS_IP" ]] && echo "  http://${TS_IP}:${PORT}/login  (Tailscale fallback)"
