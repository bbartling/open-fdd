#!/usr/bin/env bash
# Required real-stack browser tests against a disposable compose stack.
# Timescale is throwaway. Images are built from this repo. No registry pull of
# the app images, and no remote database.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

TIMESCALE_IMAGE="timescale/timescaledb:2.17.2-pg16"
WEB_BASE="http://127.0.0.1:3000"
REQUIRED_SPECS=(e2e/smoke.spec.ts e2e/product.spec.ts)
COMPOSE_FILES=(-f docker/compose.portal.yml -f docker/compose.timescale.yml -f docker/compose.ci-browser.yml)

STARTED=0

assert_disposable_project() {
  local project="$1"
  if [[ ! "$project" =~ ^openfdd-ci-browser-[A-Za-z0-9._-]+$ ]]; then
    echo "FAIL: refusing compose project" >&2
    return 1
  fi
}

assert_pull_allowed() {
  case "$1" in
    timescale/timescaledb:2.17.2-pg16) return 0 ;;
    *)
      echo "FAIL: refusing to pull image" >&2
      return 1
      ;;
  esac
}

scan_compose_config() {
  local cfg="$1"
  local project="$2"
  if grep -E -q 'ghcr\.io|railway\.internal|rlwy\.net|railway\.app' <<<"$cfg"; then
    echo "FAIL: compose config references GHCR or Railway" >&2
    return 1
  fi
  if ! grep -F -q "localhost/openfdd-ci-browser-central:${project}" <<<"$cfg"; then
    echo "FAIL: central image is not the local disposable tag" >&2
    return 1
  fi
  if ! grep -F -q "localhost/openfdd-ci-browser-web:${project}" <<<"$cfg"; then
    echo "FAIL: web image is not the local disposable tag" >&2
    return 1
  fi
  if ! grep -F -q "${TIMESCALE_IMAGE}" <<<"$cfg"; then
    echo "FAIL: timescale image is not the pinned throwaway tag" >&2
    return 1
  fi
  if ! grep -E -q 'OPENFDD_STARTER_SEED: "?0"?' <<<"$cfg"; then
    echo "FAIL: starter seed is not disabled" >&2
    return 1
  fi
  if ! grep -F -q 'postgresql://openfdd:openfdd_dev_only@timescale:5432/openfdd' <<<"$cfg"; then
    echo "FAIL: central database URL is not the compose Timescale service" >&2
    return 1
  fi
}

self_test() {
  local local_fail=0
  if assert_disposable_project "openfdd-ci-browser-123"; then
    echo "OK positive: disposable project name"
  else
    local_fail=1
  fi
  if assert_disposable_project "openfdd-portal"; then
    echo "FAIL: default portal project was accepted" >&2
    local_fail=1
  else
    echo "OK negative: refused non-disposable compose project"
  fi
  if assert_disposable_project "openfdd-ci-browser-../x"; then
    echo "FAIL: path-like project was accepted" >&2
    local_fail=1
  else
    echo "OK negative: refused path-like compose project"
  fi

  assert_pull_allowed "$TIMESCALE_IMAGE" || local_fail=1
  if assert_pull_allowed "ghcr.io/bbartling/openfdd-central:nightly"; then
    echo "FAIL: GHCR pull was accepted" >&2
    local_fail=1
  else
    echo "OK negative: refused GHCR image pull"
  fi
  if assert_pull_allowed "timescale/timescaledb:latest-pg16"; then
    echo "FAIL: unpinned timescale pull was accepted" >&2
    local_fail=1
  else
    echo "OK negative: refused unpinned timescale image"
  fi

  local project="openfdd-ci-browser-test"
  local good
  good="$(cat <<EOF
name: ${project}
services:
  central:
    image: localhost/openfdd-ci-browser-central:${project}
    environment:
      OPENFDD_DATABASE_URL: postgresql://openfdd:openfdd_dev_only@timescale:5432/openfdd
      OPENFDD_STARTER_SEED: "0"
  web:
    image: localhost/openfdd-ci-browser-web:${project}
  timescale:
    image: ${TIMESCALE_IMAGE}
EOF
)"
  if scan_compose_config "$good" "$project"; then
    echo "OK positive: local throwaway compose config"
  else
    local_fail=1
  fi
  if scan_compose_config $'image: ghcr.io/bbartling/openfdd-web:nightly\n'"$good" "$project"; then
    echo "FAIL: GHCR compose config was accepted" >&2
    local_fail=1
  else
    echo "OK negative: rejected GHCR compose config"
  fi
  if scan_compose_config $'OPENFDD_DATABASE_URL: postgresql://db.railway.internal:5432/openfdd\n'"$good" "$project"; then
    echo "FAIL: Railway database compose config was accepted" >&2
    local_fail=1
  else
    echo "OK negative: rejected Railway database compose config"
  fi

  python3 "$ROOT/scripts/ci/playwright_required_report.py" --self-test || local_fail=1
  node "$ROOT/scripts/ci/playwright_expect_reporter.cjs" --self-test || local_fail=1
  python3 "$ROOT/scripts/ci/browser_stack_health.py" --self-test || local_fail=1

  if [[ "$local_fail" -ne 0 ]]; then
    echo "real_stack_browser --self-test FAILED" >&2
    return 1
  fi
  echo "real_stack_browser --self-test OK"
}

prepare_runtime_env() {
  unset RAILWAY_ENVIRONMENT RAILWAY_PROJECT_ID RAILWAY_SERVICE_ID RAILWAY_SERVICE_NAME \
    RAILWAY_PUBLIC_DOMAIN RAILWAY_PRIVATE_DOMAIN RAILWAY_STATIC_URL || true
  unset OPENFDD_DATABASE_URL OPENFDD_CENTRAL_IMAGE OPENFDD_WEB_IMAGE OPENFDD_MCP_IMAGE \
    OPENFDD_IMAGE_TAG OPENFDD_PLAYWRIGHT_SKIP OPENFDD_GATE_BUILDING_ID \
    OPENFDD_GATE_BUILDING_IDS || true
  export OPENFDD_WEB_BIND=127.0.0.1
  export OPENFDD_CENTRAL_BIND=127.0.0.1
  export OPENFDD_CI_BROWSER_PROJECT="$PROJECT"
  export OPENFDD_CI_BROWSER_JWT_SECRET
  export OPENFDD_CI_BROWSER_ADMIN_PASSWORD
  export OPENFDD_ADMIN_PASSWORD="$OPENFDD_CI_BROWSER_ADMIN_PASSWORD"
  export OPENFDD_JWT_SECRET="$OPENFDD_CI_BROWSER_JWT_SECRET"
  export OPENFDD_PLAYWRIGHT_BASE_URL="$WEB_BASE"
  export OPENFDD_PLAYWRIGHT_REQUIRE_STACK=1
  export OPENFDD_GIT_SHA="${GITHUB_SHA:-$(git rev-parse HEAD)}"
}

redact_stream() {
  sed -e "s/${OPENFDD_CI_BROWSER_JWT_SECRET}/[redacted]/g" \
    -e "s/${OPENFDD_CI_BROWSER_ADMIN_PASSWORD}/[redacted]/g"
}

compose() {
  docker compose -p "$PROJECT" "${COMPOSE_FILES[@]}" "$@"
}

remove_disposable_project() {
  assert_disposable_project "$PROJECT"
  compose down -v --remove-orphans
  docker image rm -f \
    "localhost/openfdd-ci-browser-central:${PROJECT}" \
    "localhost/openfdd-ci-browser-web:${PROJECT}" >/dev/null 2>&1 || true
}

dump_logs() {
  compose logs --no-color --tail 80 central web timescale 2>&1 | redact_stream || true
}

require_compose() {
  local missing=0
  local tool
  for tool in docker python3 openssl git; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      echo "FAIL: required tool missing: $tool" >&2
      missing=1
    fi
  done
  if ! docker compose version >/dev/null 2>&1; then
    echo "FAIL: docker compose is required" >&2
    missing=1
  fi
  if [[ "$missing" -ne 0 ]]; then
    return 1
  fi
}

require_playwright() {
  local missing=0
  if ! command -v npx >/dev/null 2>&1; then
    echo "FAIL: required tool missing: npx" >&2
    missing=1
  fi
  if [[ ! -x frontend/web/node_modules/.bin/playwright ]]; then
    echo "FAIL: frontend/web Playwright is not installed (npm ci && playwright install)" >&2
    missing=1
  fi
  local spec
  for spec in "${REQUIRED_SPECS[@]}"; do
    if [[ ! -f "frontend/web/$spec" ]]; then
      echo "FAIL: required browser spec missing: frontend/web/$spec" >&2
      missing=1
    fi
  done
  if [[ "$missing" -ne 0 ]]; then
    return 1
  fi
}

ports_free() {
  if ! command -v ss >/dev/null 2>&1; then
    return 0
  fi
  local busy
  busy="$(ss -ltn 2>/dev/null | grep -E ':3000 |:8080 ' || true)"
  if [[ -n "$busy" ]]; then
    echo "FAIL: host port 3000 or 8080 is in use; refusing to attach to an existing stack" >&2
    printf '%s\n' "$busy" >&2
    return 1
  fi
}

rendered_config() {
  local cfg
  cfg="$(compose config)"
  scan_compose_config "$cfg" "$PROJECT"
  echo "compose config: local images, throwaway timescale, starter seed off"
}

wait_healthy() {
  local deadline=$((SECONDS + 300))
  local code=1
  while (( SECONDS < deadline )); do
    if python3 "$ROOT/scripts/ci/browser_stack_health.py" --base "$WEB_BASE"; then
      return 0
    fi
    sleep 3
  done
  echo "FAIL: disposable stack did not become healthy" >&2
  dump_logs
  return "$code"
}

run_playwright() {
  local report="$1"
  local expects="${report}.expects.json"
  local status=0
  local report_status=0
  rm -f "$expects"
  set +e
  (
    cd frontend/web
    OPENFDD_EXPECT_COUNT_FILE="$expects" \
      npx playwright test "${REQUIRED_SPECS[@]}" \
        --retries=0 \
        --reporter=json \
        --reporter="${ROOT}/scripts/ci/playwright_expect_reporter.cjs"
  ) >"$report"
  status=$?
  python3 "$ROOT/scripts/ci/playwright_required_report.py" "$report" --expects "$expects"
  report_status=$?
  rm -f "$expects"
  set -e
  echo "playwright exit ${status}; required specs: ${REQUIRED_SPECS[*]}"
  if [[ "$status" -ne 0 || "$report_status" -ne 0 ]]; then
    return 1
  fi
}

cleanup_disposable() {
  local status=$?
  trap - EXIT
  if [[ "${STARTED:-0}" -eq 1 ]]; then
    # Project-scoped volumes only. assert_disposable_project refuses any other name.
    remove_disposable_project || true
  fi
  exit "$status"
}

run_stack() {
  require_compose
  require_playwright
  ports_free
  assert_pull_allowed "$TIMESCALE_IMAGE"
  assert_disposable_project "$PROJECT"
  prepare_runtime_env
  rendered_config
  trap cleanup_disposable EXIT
  STARTED=1

  docker pull "$TIMESCALE_IMAGE"
  DOCKER_BUILDKIT=1 compose build --pull=false
  docker image inspect "localhost/openfdd-ci-browser-central:${PROJECT}" >/dev/null
  docker image inspect "localhost/openfdd-ci-browser-web:${PROJECT}" >/dev/null
  compose up -d --pull never --no-build --wait --wait-timeout 300
  wait_healthy

  local report
  report="$(mktemp)"
  if ! run_playwright "$report"; then
    dump_logs
    rm -f "$report"
    return 1
  fi
  rm -f "$report"
  echo "real_stack_browser: OK"
}

config_check() {
  require_compose
  prepare_runtime_env
  rendered_config
}

usage() {
  echo "usage: $0 [--self-test|--config-check]" >&2
}

main() {
  case "${1:-}" in
    --self-test)
      self_test
      ;;
    --config-check)
      PROJECT="${OPENFDD_CI_BROWSER_PROJECT:-openfdd-ci-browser-config}"
      OPENFDD_CI_BROWSER_JWT_SECRET="${OPENFDD_CI_BROWSER_JWT_SECRET:-$(openssl rand -hex 32)}"
      OPENFDD_CI_BROWSER_ADMIN_PASSWORD="${OPENFDD_CI_BROWSER_ADMIN_PASSWORD:-$(openssl rand -hex 24)}"
      config_check
      ;;
    --help|-h)
      usage
      ;;
    "")
      self_test
      PROJECT="openfdd-ci-browser-${GITHUB_RUN_ID:-local}-$$"
      OPENFDD_CI_BROWSER_JWT_SECRET="$(openssl rand -hex 32)"
      OPENFDD_CI_BROWSER_ADMIN_PASSWORD="$(openssl rand -hex 24)"
      run_stack
      ;;
    *)
      usage
      exit 2
      ;;
  esac
}

main "$@"
