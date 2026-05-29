#!/usr/bin/env bash
# Allow Open-FDD dashboard on LAN (run once on bensserver with sudo).
# Usage: sudo ./scripts/open_lan_port.sh [port]
set -euo pipefail
PORT="${1:-8765}"
echo "Opening TCP $PORT for Open-FDD operator dashboard…"
if command -v ufw >/dev/null 2>&1; then
  ufw allow "${PORT}/tcp" comment 'open-fdd bridge'
  ufw status | grep -E "$PORT|Status" || true
elif command -v firewall-cmd >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port="${PORT}/tcp"
  firewall-cmd --reload
  firewall-cmd --list-ports
else
  echo "No ufw/firewalld — if LAN still blocked, check iptables/nftables manually:"
  echo "  sudo iptables -I INPUT -p tcp --dport $PORT -j ACCEPT"
fi
LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "Test from another PC on the LAN:"
echo "  curl -s http://${LAN_IP:-<bensserver-ip>}:${PORT}/health"
echo "  http://${LAN_IP:-<bensserver-ip>}:${PORT}/login"
