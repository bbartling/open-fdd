#!/usr/bin/env bash
# Child-process vs verdict reconciliation for gates 25 / 25b / 26.
# Sourced by the Railway stress runner. This file does not start a scan.
security_gate_record_status() {
  local rc="${1:-}"
  local status="${2:-ERROR}"
  local report="${3:-}"
  if [[ -n "$report" && -f "$report" ]]; then
    if jq -e 'any(.checks[]?; .status=="ERROR")' "$report" >/dev/null 2>&1; then
      if [[ "$status" == "PASS" || "$status" == "BLOCKED" ]]; then
        printf '%s\n' "ERROR"
        return 0
      fi
    fi
  fi
  if [[ "$status" == "PASS" && "$rc" != "0" ]]; then
    printf '%s\n' "ERROR"
    return 0
  fi
  printf '%s\n' "$status"
}
