#!/usr/bin/env bash
# Fail if portal/local compose does not forward operator tuning env vars into central.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

CREDENTIALS_ENV_PATTERN='OPENFDD_NF_PROVIDER_CREDENTIALS_ENV|provider-credentials\.env'

required=(
  OPENFDD_INGEST_CATCHUP_HOURS
  OPENFDD_INGEST_DAILY_CATCHUP_DAYS
  OPENFDD_INGEST_PUBLICATION_DELAY_SECS
  OPENFDD_PROVIDER_TICK_SECS
  OPENFDD_AFDD_MODE
  OPENFDD_AFDD_BUILDING_ID
  OPENFDD_AFDD_BUILDING_IDS
  OPENFDD_AFDD_INTERVAL_MINUTES
  OPENFDD_AFDD_LOOKBACK_VALUE
  OPENFDD_AFDD_LOOKBACK_UNIT
)

check_source_files() {
  local fail=0
  local merged
  merged="$(cat docker/compose.portal.yml docker/compose.local.yml)"
  for name in "${required[@]}"; do
    if grep -qE "${name}: \\$\\{${name}:-\\}" <<<"$merged"; then
      echo "PASS: compose source forwards ${name}"
    else
      echo "FAIL: compose source missing \${${name}:-} forward for central" >&2
      fail=1
    fi
  done
  if grep -q 'env_file:' docker/compose.local.yml \
    && grep -qE "$CREDENTIALS_ENV_PATTERN" docker/compose.local.yml \
    && ! grep -qE 'path: \\.\\./\\.env' docker/compose.local.yml; then
    echo "PASS: compose.local.yml loads optional NF provider credentials env file only"
  else
    echo "FAIL: compose.local.yml must use OPENFDD_NF_PROVIDER_CREDENTIALS_ENV / provider-credentials.env (not repo-root .env)" >&2
    fail=1
  fi
  if [[ -f config/nf/provider-credentials.env.example ]]; then
    echo "PASS: provider-credentials.env.example is present"
  else
    echo "FAIL: missing config/nf/provider-credentials.env.example" >&2
    fail=1
  fi
  return "$fail"
}

if ! command -v docker >/dev/null 2>&1; then
  echo "NOTE: docker not installed; checking compose source only"
  if check_source_files; then
    echo "SUMMARY: PASS compose env passthrough check (source only)"
    exit 0
  fi
  echo "SUMMARY: FAIL compose env passthrough check (source only)" >&2
  exit 1
fi

COMPOSE=(
  docker compose
  -f docker/compose.portal.yml
  -f docker/compose.timescale.yml
  -f docker/compose.local.yml
)

export OPENFDD_IMAGE_TAG=sha-cicheck
export OPENFDD_TIMESCALE_PASSWORD=ci-check-only
export OPENFDD_DATABASE_URL=postgres://openfdd:ci-check-only@timescale:5432/openfdd
export OPENFDD_JWT_SECRET=ci-check-only
export OPENFDD_ADMIN_PASSWORD=ci-check-only
export OPENFDD_AGENT_PASSWORD=ci-check-only

export OPENFDD_INGEST_CATCHUP_HOURS=__ci_catchup__
export OPENFDD_INGEST_DAILY_CATCHUP_DAYS=__ci_daily__
export OPENFDD_INGEST_PUBLICATION_DELAY_SECS=__ci_pub_delay__
export OPENFDD_PROVIDER_TICK_SECS=__ci_tick__
export OPENFDD_AFDD_MODE=__ci_afdd_mode__
export OPENFDD_AFDD_BUILDING_ID=__ci_afdd_bld__
export OPENFDD_AFDD_BUILDING_IDS=__ci_afdd_blds__
export OPENFDD_AFDD_INTERVAL_MINUTES=__ci_afdd_ivl__
export OPENFDD_AFDD_LOOKBACK_VALUE=__ci_afdd_lb_val__
export OPENFDD_AFDD_LOOKBACK_UNIT=__ci_afdd_lb_unit__

config_err="$(mktemp)"
if ! config="$("${COMPOSE[@]}" config 2>"$config_err")"; then
  echo "FAIL: docker compose config failed" >&2
  cat "$config_err" >&2
  rm -f "$config_err"
  exit 1
fi
rm -f "$config_err"

central_block="$(printf '%s\n' "$config" | awk '
  /^  central:/ { in_central=1; next }
  in_central && /^  [a-z]/ && !/^  central:/ { in_central=0 }
  in_central { print }
')"

if [[ -z "$central_block" ]]; then
  echo "FAIL: could not find central service in compose config" >&2
  exit 1
fi

sentinel_for() {
  case "$1" in
    OPENFDD_INGEST_CATCHUP_HOURS) printf '%s' "$OPENFDD_INGEST_CATCHUP_HOURS" ;;
    OPENFDD_INGEST_DAILY_CATCHUP_DAYS) printf '%s' "$OPENFDD_INGEST_DAILY_CATCHUP_DAYS" ;;
    OPENFDD_INGEST_PUBLICATION_DELAY_SECS) printf '%s' "$OPENFDD_INGEST_PUBLICATION_DELAY_SECS" ;;
    OPENFDD_PROVIDER_TICK_SECS) printf '%s' "$OPENFDD_PROVIDER_TICK_SECS" ;;
    OPENFDD_AFDD_MODE) printf '%s' "$OPENFDD_AFDD_MODE" ;;
    OPENFDD_AFDD_BUILDING_ID) printf '%s' "$OPENFDD_AFDD_BUILDING_ID" ;;
    OPENFDD_AFDD_BUILDING_IDS) printf '%s' "$OPENFDD_AFDD_BUILDING_IDS" ;;
    OPENFDD_AFDD_INTERVAL_MINUTES) printf '%s' "$OPENFDD_AFDD_INTERVAL_MINUTES" ;;
    OPENFDD_AFDD_LOOKBACK_VALUE) printf '%s' "$OPENFDD_AFDD_LOOKBACK_VALUE" ;;
    OPENFDD_AFDD_LOOKBACK_UNIT) printf '%s' "$OPENFDD_AFDD_LOOKBACK_UNIT" ;;
    *) printf '' ;;
  esac
}

fail=0
for name in "${required[@]}"; do
  want="$(sentinel_for "$name")"
  if grep -qE "^      ${name}: ${want}$" <<<"$central_block"; then
    echo "PASS: central forwards ${name}"
  else
    echo "FAIL: central environment missing or wrong value for ${name} (want ${want})" >&2
    fail=1
  fi
done

if grep -q 'env_file:' docker/compose.local.yml \
  && grep -qE "$CREDENTIALS_ENV_PATTERN" docker/compose.local.yml \
  && ! grep -qE 'path: \\.\\./\\.env' docker/compose.local.yml; then
  echo "PASS: NF provider credentials use dedicated env_file path"
else
  echo "FAIL: central must load OPENFDD_NF_PROVIDER_CREDENTIALS_ENV / provider-credentials.env only" >&2
  fail=1
fi

if [[ "$fail" -ne 0 ]]; then
  echo "SUMMARY: FAIL compose env passthrough check" >&2
  exit 1
fi
echo "SUMMARY: PASS compose env passthrough check"
exit 0
