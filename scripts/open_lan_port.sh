#!/usr/bin/env bash
# Allow Open-FDD services on LAN (run once on bensserver with sudo).
# Usage: sudo ./scripts/open_lan_port.sh [port ...]
#   sudo ./scripts/open_lan_port.sh 8050 8060   # RCx Central Dash + API
set -euo pipefail
PORTS=("$@")
if [[ ${#PORTS[@]} -eq 0 ]]; then
  PORTS=(8765)
fi
for PORT in "${PORTS[@]}"; do
  echo "Opening TCP $PORT for Open-FDD…"
  if command -v ufw >/dev/null 2>&1; then
    ufw allow "${PORT}/tcp" comment 'open-fdd'
  fi
done
if command -v ufw >/dev/null 2>&1; then
  ufw status | grep -E "$(IFS='|'; echo "${PORTS[*]}")|Status" || true
elif command -v firewall-cmd >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port="${PORT}/tcp"
  firewall-cmd --reload
  firewall-cmd --list-ports
else
  echo "No ufw/firewalld — if LAN still blocked, check iptables/nftables manually:"
  echo "  sudo iptables -I INPUT -p tcp --dport $PORT -j ACCEPT"
fi
LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
TS_IP="$(ip -4 addr show tailscale0 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 || true)"
echo "Test from another PC on the LAN:"
for PORT in "${PORTS[@]}"; do
  echo "  http://${LAN_IP:-<bensserver-ip>}:${PORT}/"
done
[[ -n "$TS_IP" ]] && echo "Tailscale (if LAN blocked): http://${TS_IP}:${PORTS[0]}/"
