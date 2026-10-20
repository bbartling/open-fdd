#!/usr/bin/env bash
# Shared data-safe decisions for update and maintenance scripts.
# Destructive database or volume actions stay off unless the caller opts in.

openfdd_env_flag_on() {
  local value="${1:-}"
  value="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  case "$value" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

# openfdd_volume_prune_decision <requested 0|1> <ack 0|1>
# Prints skip, refuse, or prune. Volume prune is never the default.
openfdd_volume_prune_decision() {
  local requested="${1:-0}"
  local ack="${2:-0}"
  if [[ "$requested" != "1" ]]; then
    printf 'skip\n'
    return 0
  fi
  if [[ "$ack" != "1" ]]; then
    printf 'refuse\n'
    return 0
  fi
  printf 'prune\n'
}
