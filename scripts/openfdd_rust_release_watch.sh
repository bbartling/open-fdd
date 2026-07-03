#!/usr/bin/env bash
# Low-frequency watcher: poll GitHub Release + Rust Release workflow; re-dispatch on hard failure.
set -euo pipefail

VERSION="${1:-3.2.6}"
RUN_ID="${2:-28535265589}"
INTERVAL="${OPENFDD_RELEASE_POLL_SECS:-1800}"
MAX_RETRIES="${OPENFDD_RELEASE_MAX_RETRIES:-3}"

retries=0

release_ready() {
  gh release view "v${VERSION}" >/dev/null 2>&1
}

while true; do
  if release_ready; then
    gh release view "v${VERSION}" --json name,url,publishedAt
    exit 0
  fi

  r="$(gh run view "$RUN_ID" --json status,conclusion 2>/dev/null || echo '{}')"
  status="$(echo "$r" | jq -r '.status // "unknown"')"
  conclusion="$(echo "$r" | jq -r '.conclusion // ""')"

  if [[ -z "$conclusion" ]]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) run ${RUN_ID}: ${status} (release pending)"
    sleep "$INTERVAL"
    continue
  fi

  release_job="$(gh run view "$RUN_ID" --json jobs -q '.jobs[] | select(.name=="release") | .conclusion' 2>/dev/null || true)"
  if [[ "$release_job" == "success" ]] || release_ready; then
    gh release view "v${VERSION}" --json name,url,publishedAt 2>/dev/null || \
      echo "release job succeeded; GitHub Release page may lag"
    exit 0
  fi

  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) run ${RUN_ID} ${conclusion}; release job=${release_job:-missing}"
  gh run view "$RUN_ID" --log-failed 2>&1 | tail -15 || true

  retries=$((retries + 1))
  if [[ "$retries" -gt "$MAX_RETRIES" ]]; then
    echo "giving up after ${MAX_RETRIES} re-dispatch attempts" >&2
    exit 1
  fi

  echo "re-dispatching rust-release ${VERSION} (attempt ${retries}/${MAX_RETRIES})"
  gh workflow run rust-release.yml -f "version=${VERSION}" -f channel=beta
  sleep 90
  RUN_ID="$(gh run list --workflow=rust-release.yml --limit 1 --json databaseId -q '.[0].databaseId')"
  echo "watching new run ${RUN_ID}"
  sleep "$INTERVAL"
done
