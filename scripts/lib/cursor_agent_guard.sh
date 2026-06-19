#!/usr/bin/env bash
# Shared guards for Cursor / IDE agents — source from other scripts, do not execute directly.
#
# Cursor crashes when agents:
#   - block-wait on long shell commands (30m smokes, 3m+ pytest)
#   - poll in tight loops (sleep 60, Await, tail -f)
#   - attach to child processes that outlive the chat turn
#
# Safe pattern: systemd-run --user (or setsid) + status JSON poll scripts only.
cursor_agent_guard_is_agent() {
  [[ -n "${CURSOR_AGENT:-}" ]] || [[ -n "${CURSOR_TRACE_ID:-}" ]] || [[ "${TERM_PROGRAM:-}" == "cursor" ]]
}

cursor_agent_guard_die_if_agent_long_job() {
  local job_name="${1:-long-running job}"
  if cursor_agent_guard_is_agent; then
    cat >&2 <<EOF
REFUSED: ${job_name} cannot run attached from a Cursor agent (crashes the IDE).

Use an isolated launcher instead, then poll status (never wait/sleep/tail -f):
  ./scripts/run_paired_fdd_smoke_isolated.sh --short --bench-only
  ./scripts/smoke_paired_fdd_status.sh --mode short

  ./scripts/run_workspace_bridge_pytest_isolated.sh
  ./scripts/workspace_bridge_pytest_status.sh

See docs/operations/cursor-agent-safeguards.md
EOF
    return 1
  fi
  return 0
}

cursor_agent_guard_require_attached_flag() {
  local attached="${1:-0}"
  local job_name="${2:-long-running job}"
  if [[ "$attached" != "1" ]]; then
    return 0
  fi
  if cursor_agent_guard_is_agent; then
    cat >&2 <<EOF
REFUSED: --attached ${job_name} from a Cursor agent (crashes the IDE).
Drop --attached and use the isolated launcher + status poll scripts.
EOF
    return 1
  fi
  return 0
}
