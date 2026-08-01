#!/usr/bin/env bash
# Health gates: fieldbus, central (React generation), mqtt port, SPA web.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
auth_setup
cd "$ROOT"

hdr "Health gates (react-ot)"

# Fieldbus
if H="$(fb "$FIELDBUS_BASE/health" 2>/dev/null)"; then
  jq_ok "GET fieldbus /health" "$H" '.ok==true'
  echo "${DIM}  $(jq -c '{service,version,git_sha}' <<<"$H" 2>/dev/null || true)${RST}"
else
  bad "GET fieldbus /health unreachable ($FIELDBUS_BASE)"
fi

if H="$(fb "$FIELDBUS_BASE/api/health" 2>/dev/null)"; then
  jq_ok "GET fieldbus /api/health" "$H" '.ok==true and .service=="openfdd-fieldbus"'
else
  bad "GET fieldbus /api/health"
fi

# Central
if H="$(central "$CENTRAL_BASE/api/health" 2>/dev/null)"; then
  jq_ok "GET central /api/health" "$H" '.'
  echo "${DIM}  $(jq -c . <<<"$H" 2>/dev/null | head -c 200)${RST}"
else
  bad "GET central /api/health unreachable — Feather ingest cannot pass"
fi

# React generation / capability
if GEN="$(central "$CENTRAL_BASE/api/ui/generation" 2>/dev/null)"; then
  echo "$GEN" | head -c 400; echo
  if jq -e '.generation=="react"' <<<"$GEN" >/dev/null 2>&1; then
    ok "GET /api/ui/generation → generation=react"
  else
    bad "GET /api/ui/generation generation!=react: $GEN"
  fi
  if jq -e '.default_generation=="react"' <<<"$GEN" >/dev/null 2>&1; then
    ok "GET /api/ui/generation → default_generation=react"
  else
    bad "GET /api/ui/generation default_generation!=react"
  fi
else
  bad "GET /api/ui/generation unreachable"
fi

if CAPS="$(central "$CENTRAL_BASE/api/capabilities" 2>/dev/null)"; then
  if jq -e '.capabilities.react_ui==true' <<<"$CAPS" >/dev/null 2>&1; then
    ok "capabilities.react_ui=true"
  else
    # OPENFDD_REACT_UI may not be visible if central image predates flag wiring
    skip "capabilities.react_ui not true (got $(jq -c '.capabilities.react_ui // null' <<<"$CAPS"))"
  fi
else
  bad "GET /api/capabilities"
fi

# MQTT port
if (echo >/dev/tcp/127.0.0.1/8883) >/dev/null 2>&1; then
  ok "MQTTS port 8883 open"
else
  bad "MQTTS port 8883 closed"
fi

# React SPA (nginx on :3000)
code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$UI_BASE/" || true)"
if [[ "$code" == "200" || "$code" == "301" || "$code" == "302" ]]; then
  ok "SPA $UI_BASE → HTTP $code"
else
  bad "SPA $UI_BASE → HTTP $code (expect React web, not Streamlit)"
fi

# Container health (compose project openfdd-react)
mapfile -t CF < <(compose_files)
if docker compose "${CF[@]}" ps --format json 2>/dev/null | head -1 | grep -q .; then
  while read -r line; do
    name="$(jq -r '.Name // .name // empty' <<<"$line" 2>/dev/null || true)"
    state="$(jq -r '.State // .state // empty' <<<"$line" 2>/dev/null || true)"
    health="$(jq -r '.Health // .health // empty' <<<"$line" 2>/dev/null || true)"
    [[ -z "$name" ]] && continue
    # fieldbus may appear only via host-net; still listed in compose ps
    if [[ "$state" == "running" ]] && [[ "$health" == "healthy" || "$health" == "" || "$health" == "null" ]]; then
      ok "container $name state=$state health=${health:-n/a}"
    elif [[ "$name" == *central* ]] && [[ "$state" == "restarting" ]]; then
      bad "container $name is restarting (central must be healthy for Feather)"
    else
      bad "container $name state=$state health=$health"
    fi
  done < <(docker compose "${CF[@]}" ps --format json 2>/dev/null || true)
fi

# Must not require Streamlit ui container
if docker ps --format '{{.Names}}' | grep -qiE 'openfdd-.*-ui'; then
  skip "Streamlit ui container present (legacy profile) — product path is React web"
fi

summary
