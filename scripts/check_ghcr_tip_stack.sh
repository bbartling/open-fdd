#!/usr/bin/env bash
# Fail-closed GHCR tip completeness for Open-FDD stack.
# Hub (central/web/mqtt) must all exist for the same sha-<7>.
# Fieldbus is required by default for full tip; use --hub-only for Railway hub
# re-pin before multi-arch fieldbus finishes.
#
# Usage:
#   ./scripts/check_ghcr_tip_stack.sh sha-a40787b
#   ./scripts/check_ghcr_tip_stack.sh sha-a40787b --hub-only
#   ./scripts/check_ghcr_tip_stack.sh   # resolves tip from origin/master
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HUB_ONLY=0
TAG=""
for arg in "$@"; do
  case "$arg" in
    --hub-only) HUB_ONLY=1 ;;
    sha-*) TAG="$arg" ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$TAG" ]]; then
  if git rev-parse --verify origin/master >/dev/null 2>&1; then
    TAG="sha-$(git rev-parse --short=7 origin/master)"
  else
    TAG="sha-$(git rev-parse --short=7 HEAD)"
  fi
fi

if [[ ! "$TAG" =~ ^sha-[0-9a-f]{7}$ ]]; then
  echo "FAIL: tag must look like sha-<7 hex>, got ${TAG}" >&2
  exit 2
fi

REGISTRY="${OPENFDD_GHCR_REGISTRY:-ghcr.io/bbartling}"
HUB=(openfdd-central openfdd-web openfdd-mqtt)
EDGE=(openfdd-fieldbus)

present=()
missing=()

check_one() {
  local name="$1"
  local ref="${REGISTRY}/${name}:${TAG}"
  if docker manifest inspect "$ref" >/dev/null 2>&1; then
    present+=("$name")
    echo "OK  ${ref}"
  else
    missing+=("$name")
    echo "MISS ${ref}"
  fi
}

echo "=== GHCR tip completeness: ${TAG} (hub_only=${HUB_ONLY}) ==="
for n in "${HUB[@]}"; do check_one "$n"; done
if [[ "$HUB_ONLY" -eq 0 ]]; then
  for n in "${EDGE[@]}"; do check_one "$n"; done
fi

if [[ ${#missing[@]} -eq 0 ]]; then
  echo "PASS: tip ${TAG} complete"
  exit 0
fi

# Specific diagnosis for the Wave G hang pattern.
if printf '%s\n' "${present[@]}" | grep -qx openfdd-central \
  && printf '%s\n' "${missing[@]}" | grep -qx openfdd-mqtt; then
  echo "FAIL: PARTIAL TIP — central present but mqtt missing for ${TAG}." >&2
  echo "  Likely: Publish still on multi-arch fieldbus (or hung) before mqtt push." >&2
  echo "  Do not Railway re-pin until hub (central/web/mqtt) is complete." >&2
  exit 1
fi

echo "FAIL: incomplete tip ${TAG}; missing: ${missing[*]}" >&2
exit 1
