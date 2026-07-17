#!/usr/bin/env bash
set -euo pipefail

# Open-FDD BACnet OT NIC helper.
#
# Purpose:
# - Detect a Linux NIC/IP for BACnet.
# - Write .env values used by docker compose.
# - Optionally add a static CIDR to the NIC when explicitly requested.
#
# Safe defaults:
# - Does NOT change the NIC unless OPENFDD_BACNET_CONFIGURE_NIC=1 or --apply is used.
# - Defaults to Ben's current OT LAN observation when present:
#   <iface> / <your-ip>/24 / UDP 47808.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${OPENFDD_ENV_FILE:-$ROOT/.env}"

DEFAULT_IFACE="${OPENFDD_BACNET_IFACE:-enp3s0}"
DEFAULT_CIDR="${OPENFDD_BACNET_STATIC_CIDR:-}"
DEFAULT_PORT="${OPENFDD_BACNET_PORT:-47808}"
DEFAULT_DEVICE_INSTANCE="${OPENFDD_BACNET_DEVICE_INSTANCE:-599999}"
DEFAULT_DEVICE_NAME="${OPENFDD_BACNET_DEVICE_NAME:-OpenFDD}"

APPLY="${OPENFDD_BACNET_CONFIGURE_NIC:-0}"
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=1
fi

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

need_cmd ip

iface_exists() {
  ip link show "$1" >/dev/null 2>&1
}

cidr_on_iface() {
  local iface="$1"
  ip -o -4 addr show dev "$iface" | awk '{print $4}' | head -n1
}

detect_iface() {
  if iface_exists "$DEFAULT_IFACE"; then
    echo "$DEFAULT_IFACE"
    return
  fi

  # Prefer the interface used for the default route, then any non-loopback interface with IPv4.
  local route_iface
  route_iface="$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}' || true)"
  if [[ -n "$route_iface" ]] && iface_exists "$route_iface"; then
    echo "$route_iface"
    return
  fi

  ip -o -4 addr show scope global | awk '{print $2}' | head -n1
}

upsert_env() {
  local key="$1"
  local value="$2"
  touch "$ENV_FILE"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

IFACE="$(detect_iface)"
if [[ -z "$IFACE" ]]; then
  echo "Could not detect a BACnet NIC. Set OPENFDD_BACNET_IFACE manually." >&2
  exit 1
fi

CURRENT_CIDR="$(cidr_on_iface "$IFACE" || true)"
TARGET_CIDR="${OPENFDD_BACNET_STATIC_CIDR:-${CURRENT_CIDR:-$DEFAULT_CIDR}}"

if [[ "$APPLY" == "1" ]]; then
  if [[ -z "$CURRENT_CIDR" || "$CURRENT_CIDR" != "$TARGET_CIDR" ]]; then
    echo "Applying BACnet CIDR $TARGET_CIDR to $IFACE using sudo ip addr add..."
    sudo ip addr add "$TARGET_CIDR" dev "$IFACE" 2>/dev/null || true
    sudo ip link set "$IFACE" up
  fi
else
  echo "Dry run only. Not changing NIC. Use --apply or OPENFDD_BACNET_CONFIGURE_NIC=1 to apply."
fi

FINAL_CIDR="$(cidr_on_iface "$IFACE" || true)"
if [[ -z "$FINAL_CIDR" ]]; then
  FINAL_CIDR="$TARGET_CIDR"
fi

BIND="${FINAL_CIDR}:${DEFAULT_PORT}"

upsert_env "OPENFDD_JWT_SECRET" "${OPENFDD_JWT_SECRET:-dev-change-me-openfdd-rust-edge}"
upsert_env "OPENFDD_WORKSPACE" "/app/workspace"
upsert_env "OPENFDD_BACNET_MODE" "${OPENFDD_BACNET_MODE:-live}"
upsert_env "OPENFDD_BACNET_IFACE" "$IFACE"
upsert_env "OPENFDD_BACNET_BIND" "$BIND"
upsert_env "OPENFDD_BACNET_DEVICE_INSTANCE" "$DEFAULT_DEVICE_INSTANCE"
upsert_env "OPENFDD_BACNET_DEVICE_NAME" "$DEFAULT_DEVICE_NAME"
upsert_env "OPENFDD_BACNET_SCAN_INTERVAL_SECONDS" "${OPENFDD_BACNET_SCAN_INTERVAL_SECONDS:-3600}"
upsert_env "OPENFDD_BACNET_POLL_INTERVAL_SECONDS" "${OPENFDD_BACNET_POLL_INTERVAL_SECONDS:-60}"

echo
echo "BACnet NIC environment written to: $ENV_FILE"
echo "OPENFDD_BACNET_IFACE=$IFACE"
echo "OPENFDD_BACNET_BIND=$BIND"
echo
echo "Next (fieldbus owns BACnet/IP on host networking):"
echo "  ./scripts/openfdd_stack_up.sh standalone"
echo
echo "For a remote OT edge that attaches to a central hub, use the edge recipe:"
echo "  ./scripts/openfdd_stack_up.sh edge"
echo "  # see docs/operations/build-recipes.md"
