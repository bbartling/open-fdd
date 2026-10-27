#!/usr/bin/env bash
# CI: assert_local_stack_after_repin.sh against a stub central (T1401-1).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ASSERT="$ROOT/scripts/ops/assert_local_stack_after_repin.sh"
STUB="$ROOT/tests/ops/stub_central_server.py"
export OPENFDD_HEALTH_WAIT_SECS=5

pick_port() {
  python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
}

STUB_PID=""

start_stub() {
  local port="$1" version_json="$2"
  python3 "$STUB" "$port" "$version_json" &
  STUB_PID=$!
}

stop_stub() {
  local pid="$1"
  kill -TERM "$pid" 2>/dev/null || true
  sleep 0.1
  kill -KILL "$pid" 2>/dev/null || true
}

GOOD_VERSION='{"ok":true,"service":"openfdd-central","version":"4.0.5+c5ebca25e4f5","historian":"timescale","dual_write":false}'
BAD_VERSION='{"ok":true,"service":"openfdd-central","version":"4.0.5+deadbeef0000","historian":"timescale","dual_write":false}'
NO_VERSION='{"ok":true,"service":"openfdd-central","historian":"timescale","dual_write":false}'

run_case() {
  local label="$1" version_json="$2" expect_code="$3" sha_arg="${4:-}" grep_needle="${5:-}"
  local port base web stub_pid out code
  port="$(pick_port)"
  base="http://127.0.0.1:${port}"
  web="$base"
  start_stub "$port" "$version_json"
  stub_pid=$STUB_PID
  sleep 0.3
  set +e
  if [[ -n "$sha_arg" ]]; then
    out="$("$ASSERT" "$sha_arg" --base "$base" --web "$web" --skip-containers 2>&1)"
  else
    out="$("$ASSERT" --base "$base" --web "$web" --skip-containers 2>&1)"
  fi
  code=$?
  set -e
  stop_stub "$stub_pid"
  if [[ "$code" -ne "$expect_code" ]]; then
    echo "FAIL: $label expected exit $expect_code got $code" >&2
    printf '%s\n' "$out"
    exit 1
  fi
  if [[ -n "$grep_needle" ]] && ! grep -qE "$grep_needle" <<<"$out"; then
    echo "FAIL: $label missing expected output: $grep_needle" >&2
    printf '%s\n' "$out"
    exit 1
  fi
  echo "PASS: $label"
}

run_case "matching version exits 0" "$GOOD_VERSION" 0 sha-c5ebca2 'PASS: version carries c5ebca2'
run_case "wrong sha exits non-zero" "$BAD_VERSION" 2 sha-c5ebca2 'FAIL: version'
run_case "missing version field exits non-zero" "$NO_VERSION" 2 '' 'FAIL: GET .*/api/version missing version field'

dead_port="$(pick_port)"
set +e
out="$(OPENFDD_HEALTH_WAIT_SECS=3 "$ASSERT" --base "http://127.0.0.1:${dead_port}" --web "http://127.0.0.1:${dead_port}" --skip-containers 2>&1)"
code=$?
set -e
if [[ "$code" -eq 0 ]]; then
  echo "FAIL: unreachable host should not exit 0" >&2
  exit 1
fi
grep -qE 'FAIL: GET .*/api/health' <<<"$out" || {
  echo "FAIL: unreachable host should print health FAIL" >&2
  printf '%s\n' "$out"
  exit 1
}
echo "PASS: unreachable host exits non-zero with FAIL line"

echo "OK tests/ops/test_assert_local_stack.sh"
