#!/usr/bin/env bash
# Optional retention sidecar — calls data-management API only (never deletes Feather directly).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_BASE="${OPENFDD_RETENTION_API_BASE:-http://127.0.0.1:8080}"
POLICY="${OPENFDD_RETENTION_POLICY_FILE:-$ROOT/workspace/data-management/retention.local.toml}"
DRY_RUN="${OPENFDD_RETENTION_DRY_RUN:-1}"
ENABLED="${OPENFDD_RETENTION_SIDECAR_ENABLED:-0}"
AUTH_ENV="${OPENFDD_RETENTION_AUTH_ENV:-$ROOT/workspace/auth.env.local}"

[[ "$ENABLED" == "1" ]] || { echo "retention sidecar disabled (set OPENFDD_RETENTION_SIDECAR_ENABLED=1)"; exit 0; }
[[ -f "$POLICY" ]] || { echo "no policy at $POLICY — skipping"; exit 0; }

login() {
  local pw
  pw="$(grep '^OFDD_INTEGRATOR_PASSWORD=' "$AUTH_ENV" | cut -d= -f2- | tr -d '\r')"
  curl -fsS -X POST "$API_BASE/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u integrator --arg p "$pw" '{username:$u,password:$p}')" \
    | jq -r '.token // .access_token'
}

TOKEN="$(login)"
echo "Retention sidecar: policy=$POLICY dry_run=$DRY_RUN"

# Example policy hook: purge validation historian rows older than configured days.
# Full TOML parsing belongs in a future release; operators can call preview/execute via API/UI today.
if grep -q 'validation_days' "$POLICY" 2>/dev/null; then
  days="$(grep '^validation_days' "$POLICY" | head -1 | cut -d= -f2 | tr -d ' ')"
  before="$(date -u -d "-${days} days" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-"${days}"d +%Y-%m-%dT%H:%M:%SZ)"
  preview="$(curl -fsS -X POST "$API_BASE/api/data-management/purge/preview" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg b "$before" '{historian_subdir:"validation",before_utc:$b,dry_run:true}')")"
  echo "$preview" | jq .
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "DRY_RUN=1 — no execute"
    exit 0
  fi
  curl -fsS -X POST "$API_BASE/api/data-management/purge/execute" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg b "$before" --arg c 'PURGE HISTORIAN DATA' '{historian_subdir:"validation",before_utc:$b,dry_run:false,confirmation:$c}')" \
    | jq .
fi
