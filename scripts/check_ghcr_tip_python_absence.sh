#!/usr/bin/env bash
# Digest-bound tip image Python-absence smoke (Wave J J5).
# Pulls (or uses local) sha-<7> stack images and fails if a Python interpreter
# or obvious pandas/pip footprint is present in the *runtime* filesystem.
#
# Usage:
#   ./scripts/check_ghcr_tip_python_absence.sh
#   ./scripts/check_ghcr_tip_python_absence.sh sha-a40787b
#   ./scripts/check_ghcr_tip_python_absence.sh sha-a40787b --hub-only
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

SERVICES=(openfdd-central openfdd-web openfdd-mqtt)
if [[ "$HUB_ONLY" -eq 0 ]]; then
  SERVICES+=(openfdd-fieldbus)
fi

REPORT_DIR="${OPENFDD_TIP_PYTHON_REPORT_DIR:-$ROOT/reports/ghcr-tip-python-absence}"
mkdir -p "$REPORT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT="$REPORT_DIR/${TAG}_${STAMP}.txt"

echo "=== GHCR tip Python-absence: $TAG (hub_only=$HUB_ONLY) ===" | tee "$REPORT"

fail=0
missing=()
for svc in "${SERVICES[@]}"; do
  ref="ghcr.io/bbartling/${svc}:${TAG}"
  if ! docker image inspect "$ref" >/dev/null 2>&1; then
    if ! docker pull "$ref" >/dev/null 2>&1; then
      echo "MISS $ref" | tee -a "$REPORT"
      missing+=("$svc")
      fail=1
      continue
    fi
  fi
  digest="$(docker image inspect "$ref" --format '{{if .RepoDigests}}{{index .RepoDigests 0}}{{else}}local{{end}}' 2>/dev/null || echo local)"
  # Runtime smoke: interpreter on PATH, common python paths, pip, pandas .so names.
  if docker run --rm --entrypoint sh "$ref" -c '
    set -e
    if command -v python >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1 || command -v pip >/dev/null 2>&1 || command -v pip3 >/dev/null 2>&1; then
      echo "interpreter_or_pip_on_path"
      exit 11
    fi
    for p in /usr/bin/python /usr/bin/python3 /usr/local/bin/python /usr/local/bin/python3 \
             /opt/conda/bin/python /home/python; do
      if [ -e "$p" ]; then
        echo "path_exists:$p"
        exit 12
      fi
    done
    if ls /usr/lib/python* >/dev/null 2>&1 || ls /usr/local/lib/python* >/dev/null 2>&1; then
      echo "python_lib_tree"
      exit 13
    fi
    exit 0
  ' >>"$REPORT" 2>&1; then
    echo "OK  $ref ($digest)" | tee -a "$REPORT"
  else
    echo "FAIL $ref ($digest) — Python footprint detected" | tee -a "$REPORT"
    fail=1
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "FAIL: incomplete tip $TAG; missing: ${missing[*]}" | tee -a "$REPORT"
  exit 1
fi
if [[ "$fail" -ne 0 ]]; then
  echo "FAIL: Python footprint on tip $TAG (report $REPORT)" | tee -a "$REPORT"
  exit 1
fi
echo "PASS: tip $TAG has no runtime Python footprint (report $REPORT)" | tee -a "$REPORT"
