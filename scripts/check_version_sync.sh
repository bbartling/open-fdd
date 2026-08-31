#!/usr/bin/env bash
# Fail when VERSION drifts from workspace / published crate versions.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION_FILE="$(tr -d '[:space:]' < VERSION)"
WORKSPACE_VER="$(grep -E '^version = ' Cargo.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"

if [[ "$VERSION_FILE" != "$WORKSPACE_VER" ]]; then
  echo "FAIL: VERSION ($VERSION_FILE) != workspace Cargo.toml ($WORKSPACE_VER)" >&2
  exit 1
fi

MISMATCH=0
while IFS= read -r f; do
  pkg_ver="$(grep -E '^version = ' "$f" | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
  if [[ "$pkg_ver" != "$VERSION_FILE" ]]; then
    echo "FAIL: $f version=$pkg_ver expected $VERSION_FILE" >&2
    MISMATCH=1
  fi
done < <(find edge services crates/openfdd_contracts crates/openfdd_mqtt -name Cargo.toml 2>/dev/null)

if [[ "$MISMATCH" != "0" ]]; then
  exit 1
fi

echo "OK: VERSION and Cargo.toml versions match ($VERSION_FILE)"
