#!/usr/bin/env bash
# Shared SSH/rsync options for edge host access from bensserver (control machine).
# shellcheck shell=bash
#
# Prefers key-based auth when available; falls back to SSHPASS + sshpass password auth.

build_edge_ssh_cmd() {
  local -a opts=(-o ConnectTimeout="${EDGE_SSH_CONNECT_TIMEOUT:-12}" -o BatchMode=yes)
  EDGE_SSH_CMD=(ssh "${opts[@]}")
  EDGE_SSH_PASS_CMD=()
  if [[ -n "${SSHPASS:-}" ]] && command -v sshpass >/dev/null 2>&1; then
    export SSHPASS
    EDGE_SSH_PASS_CMD=(sshpass -e ssh "${opts[@]}" -o PreferredAuthentications=password -o PubkeyAuthentication=no)
  fi
}

# Run remote command; tries key auth first, then password when SSHPASS is configured.
edge_ssh_run() {
  local target="$1"
  shift
  build_edge_ssh_cmd
  if "${EDGE_SSH_CMD[@]}" "$target" "$@" 2>/dev/null; then
    return 0
  fi
  if [[ ${#EDGE_SSH_PASS_CMD[@]} -gt 0 ]]; then
    "${EDGE_SSH_PASS_CMD[@]}" "$target" "$@"
    return $?
  fi
  return 255
}

build_edge_rsync_ssh() {
  build_edge_ssh_cmd
  local target="${EDGE_RSYNC_PROBE_TARGET:-}"
  local -a cmd=("${EDGE_SSH_CMD[@]}")
  if [[ -n "$target" ]] && ! "${EDGE_SSH_CMD[@]}" "$target" true 2>/dev/null; then
    if [[ ${#EDGE_SSH_PASS_CMD[@]} -gt 0 ]]; then
      cmd=("${EDGE_SSH_PASS_CMD[@]}")
    fi
  fi
  EDGE_RSYNC_SSH=()
  local part
  for part in "${cmd[@]}"; do
    EDGE_RSYNC_SSH+=("$(printf '%q' "$part")")
  done
}
