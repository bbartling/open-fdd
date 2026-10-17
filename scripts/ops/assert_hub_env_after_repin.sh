#!/usr/bin/env bash
# Soft-OPEN: assert Railway hub env + MQTT TCP proxy after every re-pin.
# Usage: ./scripts/ops/assert_hub_env_after_repin.sh [sha-<7>]
# Exit 0 = PASS, 2 = FAIL. Soft-OPEN ≠ FQ. No backups. No volume deletes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXPECT_SHA="${1:-${OPENFDD_IMAGE_TAG:-}}"
HUB_BASE="${OPENFDD_API_BASE:-https://openfdd-web-production.up.railway.app}"
HUB_BASE="${HUB_BASE%/}"
FAIL=0

say() { printf '%s\n' "$*"; }
fail() { say "FAIL: $*"; FAIL=1; }
pass() { say "PASS: $*"; }

say "== Soft-OPEN hub env assert =="
say "hub=$HUB_BASE expect_sha=${EXPECT_SHA:-<any>}"

if ! command -v railway >/dev/null 2>&1; then
  fail "railway CLI not on PATH"
else
  for svc in openfdd-central openfdd-web openfdd-mqtt; do
    if railway variables -s "$svc" --json >/tmp/openfdd_hub_env_"$svc".json 2>/dev/null; then
      pass "railway variables readable for $svc"
    else
      fail "cannot read railway variables for $svc"
    fi
  done
fi

_proxy_list=""
_live_port=""
if command -v railway >/dev/null 2>&1; then
  _proxy_list="$(railway tcp-proxy list -s openfdd-mqtt 2>/dev/null || true)"
  _live_port="$(printf '%s\n' "$_proxy_list" | grep -oE ':[0-9]+' | head -1 | tr -d ':')"
fi
if [[ -z "$_live_port" ]]; then
  fail "no live openfdd-mqtt TCP proxy port (do not use 44763)"
elif [[ "$_live_port" == "44763" ]]; then
  fail "proxy still lists dead port 44763"
else
  pass "MQTT TCP proxy port=$_live_port"
fi

health="$(curl -sf --max-time 20 "$HUB_BASE/api/health" || true)"
if [[ -z "$health" ]]; then
  fail "GET $HUB_BASE/api/health empty or failed"
else
  say "health=$health"
  echo "$health" | grep -qi timescale && pass "historian timescale" || fail "historian not timescale"
  echo "$health" | grep -qiE '"dual_write"[[:space:]]*:[[:space:]]*false' \
    && pass "dual_write false" || fail "dual_write not false"
  if [[ -n "$EXPECT_SHA" ]]; then
    short="${EXPECT_SHA#sha-}"
    echo "$health" | grep -q "$short" && pass "health mentions $short" || fail "health missing $short"
  fi
fi

afdd="$(curl -sf --max-time 20 -o /tmp/openfdd_afdd_status.json -w '%{http_code}' \
  "$HUB_BASE/api/afdd/scheduler/status" || true)"
if [[ "$afdd" == "200" ]]; then
  pass "AFDD scheduler status 200"
else
  fail "AFDD scheduler status HTTP ${afdd:-none}"
fi

# Multi-tenant / workspace keys (best-effort when railway JSON dump exists).
if [[ -f /tmp/openfdd_hub_env_openfdd-central.json ]]; then
  for key in OPENFDD_WORKSPACE OPENFDD_STORAGE_URL OPENFDD_MULTI_TENANT; do
    if grep -q "\"$key\"" /tmp/openfdd_hub_env_openfdd-central.json 2>/dev/null; then
      pass "central has $key"
    else
      say "WARN: central JSON dump missing $key (check Railway UI)"
    fi
  done
fi

if [[ "$FAIL" -ne 0 ]]; then
  say "RESULT=FAIL"
  exit 2
fi
say "RESULT=PASS"
exit 0
