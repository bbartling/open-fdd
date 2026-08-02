#!/usr/bin/env bash
# P1-M1-C: inspect openfdd-web (+ optional central) for no Python runtime and
# required SPA/version evidence. Does not require a clean VM — local docker is OK.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TAG="${OPENFDD_IMAGE_TAG:-nightly}"
WEB_IMAGE="${OPENFDD_WEB_IMAGE:-ghcr.io/bbartling/openfdd-web:${TAG}}"
CENTRAL_IMAGE="${OPENFDD_CENTRAL_IMAGE:-ghcr.io/bbartling/openfdd-central:${TAG}}"
OUT_DIR="${1:-reports/p1_m1_web_smoke}"
mkdir -p "$OUT_DIR"

echo "== P1-M1 web image smoke =="
echo "web=$WEB_IMAGE"
echo "central=$CENTRAL_IMAGE"

if ! docker image inspect "$WEB_IMAGE" >/dev/null 2>&1; then
  docker pull "$WEB_IMAGE"
fi
docker image inspect "$WEB_IMAGE" >"$OUT_DIR/web_inspect.json"
digest="$(docker image inspect "$WEB_IMAGE" --format '{{index .RepoDigests 0}}' 2>/dev/null || true)"
echo "web_digest=${digest:-unknown}" | tee "$OUT_DIR/web_digest.txt"

# No Python interpreter in the web image.
if docker run --rm --entrypoint sh "$WEB_IMAGE" -c 'command -v python3 || command -v python || command -v python3.12' 2>/dev/null; then
  echo "FAIL: python found in openfdd-web image" >&2
  exit 1
fi
echo "OK: no python binary in openfdd-web"

# version.json present
ver="$(docker run --rm --entrypoint cat "$WEB_IMAGE" /usr/share/nginx/html/version.json)"
echo "$ver" | tee "$OUT_DIR/version.json"
echo "$ver" | grep -q '"service":"openfdd-web"'
echo "OK: version.json present"

# Optional: central has no python either (Rust binary image).
if docker pull "$CENTRAL_IMAGE" >/dev/null 2>&1; then
  if docker run --rm --entrypoint sh "$CENTRAL_IMAGE" -c 'command -v python3 || command -v python' 2>/dev/null; then
    echo "FAIL: python found in openfdd-central" >&2
    exit 1
  fi
  echo "OK: no python binary in openfdd-central"
  docker image inspect "$CENTRAL_IMAGE" >"$OUT_DIR/central_inspect.json"
fi

# Local compose-build path when GHCR web tag missing (dev):
# docker build -t openfdd-web:local frontend/web && OPENFDD_WEB_IMAGE=openfdd-web:local …

cat >"$OUT_DIR/SUMMARY.md" <<EOF
# P1-M1-C web image smoke

- web: \`$WEB_IMAGE\`
- digest: \`${digest:-unknown}\`
- no python in web: PASS
- version.json: present

Recreate:
\`\`\`bash
OPENFDD_IMAGE_TAG=$TAG ./scripts/release/smoke_react_web_image.sh
\`\`\`
EOF

echo "Report: $OUT_DIR/SUMMARY.md"
