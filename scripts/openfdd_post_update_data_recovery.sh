#!/usr/bin/env bash
# Post site-update recovery: container UID ownership for historian + feather stores (FIX-47).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"

WS="$ROOT/workspace"
UID_NUM="$(openfdd_rust_container_uid)"
GID_NUM="${OPENFDD_CONTAINER_GID:-$UID_NUM}"

echo "==> openfdd_post_update_data_recovery (uid=${UID_NUM})"

mkdir -p \
  "$WS/data/historian/validation" \
  "$WS/data/feather_store/modbus" \
  "$WS/data/feather_store/bacnet" \
  "$WS/data/drivers/bacnet" \
  "$WS/reports/generated" \
  "$WS/logs"

AUTH="$WS/auth.env.local"
if [[ -f "$AUTH" ]]; then
  chmod 644 "$AUTH" 2>/dev/null || true
fi

chown_paths() {
  local paths=("$@")
  if [[ "$(id -u)" -eq 0 ]]; then
    chown -R "${UID_NUM}:${GID_NUM}" "${paths[@]}" 2>/dev/null || true
  elif command -v sudo >/dev/null 2>&1; then
    sudo chown -R "${UID_NUM}:${GID_NUM}" "${paths[@]}" 2>/dev/null || true
  else
    echo "WARN: cannot chown — run: sudo chown -R ${UID_NUM}:${GID_NUM} $WS/data" >&2
  fi
}

chown_paths \
  "$WS/data/historian" \
  "$WS/data/feather_store" \
  "$WS/data/drivers" \
  "$WS/reports" \
  "$WS/logs"

echo "Recovery OK — historian + feather_store owned by container uid ${UID_NUM}"
