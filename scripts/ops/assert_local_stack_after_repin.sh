#!/usr/bin/env bash
# Assert the local single-host Open-FDD stack after a re-pin.
#
# Usage:
#   ./scripts/ops/assert_local_stack_after_repin.sh [sha-<7>] [--base URL] [--web URL] [--env-file PATH] [--skip-containers]
#
# Checks (read-only): /api/health ok, Timescale historian, dual_write false,
# /api/version carries the expected sha, AFDD scheduler status reachable,
# web SPA answers, and (unless --skip-containers) running central/web containers
# use the pinned tag.
# Base URL defaults to http://127.0.0.1:8080 (OPENFDD_API_BASE overrides);
# web defaults to http://127.0.0.1:3000 (OPENFDD_WEB_BASE overrides).
# Exit 0 = PASS, 2 = FAIL. Never prints secrets.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT/.env"
BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
WEB="${OPENFDD_WEB_BASE:-http://127.0.0.1:3000}"
EXPECT_SHA="${OPENFDD_IMAGE_TAG:-}"
HEALTH_WAIT_SECS="${OPENFDD_HEALTH_WAIT_SECS:-180}"
SKIP_CONTAINERS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    sha-*) EXPECT_SHA="$1" ;;
    --base) BASE="$2"; shift ;;
    --web) WEB="$2"; shift ;;
    --env-file) ENV_FILE="$2"; shift ;;
    --skip-containers) SKIP_CONTAINERS=1 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done
BASE="${BASE%/}"
WEB="${WEB%/}"
if [[ -z "$EXPECT_SHA" && -f "$ENV_FILE" ]]; then
  EXPECT_SHA="$(grep -E '^OPENFDD_IMAGE_TAG=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"
fi

FAIL=0
say() { printf '%s\n' "$*"; }
fail() { say "FAIL: $*"; FAIL=1; }
pass() { say "PASS: $*"; }

json_field() {
  local json="$1" field="$2"
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$json" | jq -r --arg f "$field" '.[$f] // empty' 2>/dev/null || true
    return 0
  fi
  local line
  if ! line="$(printf '%s' "$json" | grep -oE "\"${field}\"[[:space:]]*:[[:space:]]*\"[^\"]+\"" | head -1)"; then
    printf ''
    return 0
  fi
  sed -E 's/.*"([^"]+)"$/\1/' <<<"$line"
}

say "== local stack assert: base=$BASE web=$WEB expect=${EXPECT_SHA:-<any>}"

health=""
deadline=$((SECONDS + HEALTH_WAIT_SECS))
while [[ $SECONDS -lt $deadline ]]; do
  health="$(curl -sf --max-time 10 "$BASE/api/health" || true)"
  [[ -n "$health" ]] && break
  sleep 5
done

if [[ -z "$health" ]]; then
  fail "GET $BASE/api/health empty or failed after ${HEALTH_WAIT_SECS}s"
else
  if printf '%s' "$health" | grep -qE '"ok"[[:space:]]*:[[:space:]]*true'; then
    pass "health ok"
  else
    fail "health ok!=true"
  fi
  if printf '%s' "$health" | grep -qE '"historian"[[:space:]]*:[[:space:]]*"timescale"'; then
    pass "historian timescale"
  else
    fail "historian not timescale"
  fi
  if printf '%s' "$health" | grep -qE '"dual_write"[[:space:]]*:[[:space:]]*false'; then
    pass "dual_write false"
  else
    fail "dual_write not false"
  fi
fi

version_json=""
version_deadline=$((SECONDS + HEALTH_WAIT_SECS))
while [[ $SECONDS -lt $version_deadline ]]; do
  version_json="$(curl -sf --max-time 10 "$BASE/api/version" || true)"
  [[ -n "$version_json" ]] && break
  sleep 5
done

if [[ -z "$version_json" ]]; then
  fail "GET $BASE/api/version empty or failed after ${HEALTH_WAIT_SECS}s"
else
  version="$(json_field "$version_json" version)"
  say "version=${version:-<missing>}"
  if [[ -z "$version" ]]; then
    fail "GET $BASE/api/version missing version field"
  elif [[ -n "$EXPECT_SHA" ]]; then
    short="${EXPECT_SHA#sha-}"
    if [[ "$version" == *"+${short}"* ]]; then
      pass "version carries $short"
    else
      fail "version ${version} does not carry $short"
    fi
  else
    pass "version present"
  fi
fi

code="$(curl -s --max-time 20 -o /dev/null -w '%{http_code}' "$BASE/api/afdd/scheduler/status" || true)"
case "$code" in
  200|401|403) pass "AFDD scheduler status reachable (HTTP $code)" ;;
  *) fail "AFDD scheduler status HTTP ${code:-none}" ;;
esac

code="$(curl -s --max-time 20 -o /dev/null -w '%{http_code}' "$WEB/" || true)"
[[ "$code" == "200" ]] && pass "web SPA $WEB/ 200" || fail "web SPA $WEB/ HTTP ${code:-none}"

if [[ "$SKIP_CONTAINERS" -eq 0 && -n "$EXPECT_SHA" ]] && command -v docker >/dev/null 2>&1; then
  project=""
  [[ -f "$ENV_FILE" ]] && project="$(grep -E '^COMPOSE_PROJECT_NAME=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"
  for svc in central web; do
    filter=(--filter "label=com.docker.compose.service=$svc")
    [[ -n "$project" ]] && filter+=(--filter "label=com.docker.compose.project=$project")
    img="$(docker ps "${filter[@]}" --format '{{.Image}}' | head -1)"
    if [[ -z "$img" ]]; then
      fail "no running $svc container${project:+ in project $project}"
    elif [[ "$img" == *":$EXPECT_SHA" ]]; then
      pass "$svc image $img"
    else
      fail "$svc image $img is not :$EXPECT_SHA"
    fi
  done
fi

if [[ "$FAIL" -ne 0 ]]; then
  say "SUMMARY: FAIL (one or more checks failed)"
  exit 2
fi
say "SUMMARY: PASS (all checks ok)"
exit 0
