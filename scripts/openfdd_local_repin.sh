#!/usr/bin/env bash
# Re-pin the local single-host Open-FDD stack to a published GHCR sha-<7>.
#
# The hosted stack is one local host running from the repo checkout:
#   docker compose --env-file .env -f docker/compose.portal.yml \
#     -f docker/compose.timescale.yml -f docker/compose.local.yml up -d --no-build
# Secrets and the pin live in the gitignored repo-root .env
# (COMPOSE_PROJECT_NAME, OPENFDD_IMAGE_TAG, ...).
#
# Usage:
#   ./scripts/openfdd_local_repin.sh sha-1234567           # pin, pull, up, assert
#   ./scripts/openfdd_local_repin.sh                       # resolve newest-by-created
#   ./scripts/openfdd_local_repin.sh sha-1234567 --dry-run # print the plan only
#
# Options:
#   --env-file PATH     env file to edit (default: <repo>/.env)
#   --base URL          central base URL for the post-up assert (default http://127.0.0.1:8080)
#   --skip-tip-gate     do not run scripts/check_ghcr_tip_stack.sh first
#   --dry-run           change nothing
#
# Data safety: edits only the OPENFDD_IMAGE_TAG line, never builds images,
# never runs `down`, never removes volumes, never prunes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
TAG=""
DRY=0
TIP_GATE=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    sha-*) TAG="$1" ;;
    --env-file) ENV_FILE="$2"; shift ;;
    --base) BASE="$2"; shift ;;
    --skip-tip-gate) TIP_GATE=0 ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,23p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

if [[ ! -f "$ENV_FILE" ]]; then
  echo "FAIL: env file not found: $ENV_FILE (copy .env.example and fill secrets)" >&2
  exit 2
fi

if [[ -z "$TAG" ]]; then
  TAG="$("$ROOT/scripts/ghcr_newest_by_created.py" openfdd-central | awk -F'\t' 'NR==1{print $2}')"
  web_tag="$("$ROOT/scripts/ghcr_newest_by_created.py" openfdd-web | awk -F'\t' 'NR==1{print $2}')"
  if [[ "$TAG" != "$web_tag" ]]; then
    echo "FAIL: newest central ($TAG) and web ($web_tag) differ; pass an explicit sha-<7>" >&2
    exit 2
  fi
fi
if [[ ! "$TAG" =~ ^sha-[0-9a-f]{7}$ ]]; then
  echo "FAIL: tag must look like sha-<7 hex>, got '${TAG}'" >&2
  exit 2
fi

old="$(grep -E '^OPENFDD_IMAGE_TAG=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"
COMPOSE=(docker compose --env-file "$ENV_FILE"
  -f "$ROOT/docker/compose.portal.yml"
  -f "$ROOT/docker/compose.timescale.yml"
  -f "$ROOT/docker/compose.local.yml")

echo "== local re-pin: ${old:-<unset>} -> ${TAG} (env=$ENV_FILE base=$BASE)"
if [[ "$DRY" -eq 1 ]]; then
  echo "DRY-RUN: would run tip gate=${TIP_GATE}, set OPENFDD_IMAGE_TAG=${TAG},"
  echo "  ${COMPOSE[*]} pull central web"
  echo "  ${COMPOSE[*]} up -d --no-build"
  echo "  scripts/ops/assert_local_stack_after_repin.sh ${TAG} --base ${BASE}"
  exit 0
fi

if [[ "$TIP_GATE" -eq 1 ]]; then
  "$ROOT/scripts/check_ghcr_tip_stack.sh" "$TAG"
fi

tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
if grep -qE '^OPENFDD_IMAGE_TAG=' "$ENV_FILE"; then
  sed -E "s/^OPENFDD_IMAGE_TAG=.*/OPENFDD_IMAGE_TAG=${TAG}/" "$ENV_FILE" >"$tmp"
else
  cat "$ENV_FILE" >"$tmp"
  printf 'OPENFDD_IMAGE_TAG=%s\n' "$TAG" >>"$tmp"
fi
chmod --reference="$ENV_FILE" "$tmp" 2>/dev/null || chmod 600 "$tmp"
mv "$tmp" "$ENV_FILE"
echo "OK: OPENFDD_IMAGE_TAG=${TAG} written (previous: ${old:-<unset>})"

(cd "$ROOT" && "${COMPOSE[@]}" pull central web)
(cd "$ROOT" && "${COMPOSE[@]}" up -d --no-build)

"$ROOT/scripts/ops/assert_local_stack_after_repin.sh" "$TAG" --base "$BASE" --env-file "$ENV_FILE"
