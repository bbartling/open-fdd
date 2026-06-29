#!/usr/bin/env bash
# Call CSV import preflight API (read-only validation gate).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/openfdd_auth_lib.sh"

SESSION_ID="${1:-}"
if [[ -z "$SESSION_ID" ]]; then
  echo "usage: $0 <session_id>" >&2
  exit 1
fi

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
TOKEN="$(openfdd_auth_login_token integrator)"

curl -sS -X POST "$BASE/api/csv/import/preflight" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg sid "$SESSION_ID" '{session_id:$sid}')" \
  | jq '{ok, session_id, verdict, can_execute, checks: .validation.checks, agent_hints: .validation.agent_hints}'
