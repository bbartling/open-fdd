#!/usr/bin/env bash
# Positive and negative controls for scripts/ci/forbid_datafusion_product.sh.
# A cargo tree failure must fail the guard. A clean tree must not.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GUARD="$ROOT/scripts/ci/forbid_datafusion_product.sh"
fail=0

run_expect_fail() {
  local name="$1"
  shift
  local output status
  set +e
  output="$("$@" 2>&1)"
  status=$?
  set -e
  if [[ "$status" -eq 0 ]]; then
    echo "FAIL: ${name} expected a non-zero exit"
    printf '%s\n' "$output"
    fail=1
    return
  fi
  if ! grep -q 'FAIL:' <<<"$output"; then
    echo "FAIL: ${name} expected a FAIL: line (exit ${status})"
    printf '%s\n' "$output"
    fail=1
    return
  fi
  echo "OK negative: ${name} (exit ${status})"
}

run_expect_ok() {
  local name="$1"
  shift
  local output status
  set +e
  output="$("$@" 2>&1)"
  status=$?
  set -e
  if [[ "$status" -ne 0 ]]; then
    echo "FAIL: ${name} expected exit 0 (got ${status})"
    printf '%s\n' "$output"
    fail=1
    return
  fi
  if ! grep -q 'forbid_datafusion_product: OK' <<<"$output"; then
    echo "FAIL: ${name} expected the guard OK line"
    printf '%s\n' "$output"
    fail=1
    return
  fi
  echo "OK positive: ${name}"
}

write_fake_cargo() {
  local dir="$1"
  local body="$2"
  mkdir -p "$dir"
  cat >"$dir/cargo" <<EOF
#!/bin/sh
${body}
EOF
  chmod 755 "$dir/cargo"
}

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

clean_dir="$tmp/clean"
write_fake_cargo "$clean_dir" 'printf "%s\n" "openfdd-central v0.0.0" "anyhow v1.0.0"
exit 0'
run_expect_ok "clean cargo tree" env PATH="${clean_dir}:$PATH" bash "$GUARD"

nonzero_dir="$tmp/nonzero"
write_fake_cargo "$nonzero_dir" 'echo "error: package ID specification did not match any packages" >&2
exit 101'
run_expect_fail "cargo tree non-zero exit" env PATH="${nonzero_dir}:$PATH" bash "$GUARD"

error_text_dir="$tmp/error-text"
write_fake_cargo "$error_text_dir" 'echo "error: simulated cargo tree failure" >&2
printf "%s\n" "openfdd-central v0.0.0"
exit 0'
run_expect_fail "cargo tree error text with exit 0" env PATH="${error_text_dir}:$PATH" bash "$GUARD"

empty_dir="$tmp/empty"
write_fake_cargo "$empty_dir" 'exit 0'
run_expect_fail "cargo tree empty package list" env PATH="${empty_dir}:$PATH" bash "$GUARD"

datafusion_dir="$tmp/datafusion"
write_fake_cargo "$datafusion_dir" 'printf "%s\n" "openfdd-central v0.0.0" "datafusion v50.0.0"
exit 0'
run_expect_fail "cargo tree lists datafusion" env PATH="${datafusion_dir}:$PATH" bash "$GUARD"

if ! command -v cargo >/dev/null 2>&1; then
  echo "FAIL: real cargo is not on PATH; positive cargo tree control did not run"
  fail=1
else
  run_expect_ok "real cargo tree" bash "$GUARD"
fi

if [[ "$fail" -ne 0 ]]; then
  echo "test_forbid_datafusion_product: FAILED"
  exit 1
fi
echo "test_forbid_datafusion_product: OK (positive=2 negative=4)"
