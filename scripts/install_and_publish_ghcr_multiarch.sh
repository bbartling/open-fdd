#!/usr/bin/env bash
# Install multi-arch GHCR publish workflow, push, dispatch, verify arm64 manifests.
# Requires: gh CLI logged in with `workflow` scope (gh auth refresh -h github.com -s workflow)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
TAG="${1:-3.1.6}"
WF_SRC="$ROOT/scripts/ghcr-multiarch-publish.workflow.yml"
WF_DST="$ROOT/.github/workflows/ghcr-multiarch-publish.yml"

scopes="$(gh auth status 2>&1 | grep -o "Token scopes:.*" || true)"
if [[ "$scopes" != *workflow* ]]; then
  echo "ERROR: gh token needs workflow scope. Run:" >&2
  echo "  gh auth refresh -h github.com -s workflow" >&2
  exit 1
fi

mkdir -p "$(dirname "$WF_DST")"
cp "$WF_SRC" "$WF_DST"
git add "$WF_DST"
if git diff --cached --quiet; then
  echo "Workflow already installed."
else
  git commit -m "ci: add multi-arch GHCR publish workflow"
  git push origin HEAD:master
fi

gh workflow run "Publish multi-arch GHCR images" -f "image_tag=${TAG}"
echo "Dispatched publish for tag=${TAG}. Waiting for run…"
sleep 15
RUN_ID="$(gh run list --workflow ghcr-multiarch-publish.yml --limit 1 --json databaseId -q '.[0].databaseId')"
gh run watch "$RUN_ID" --exit-status

verify() {
  local image="$1"
  local token
  token="$(curl -fsSL "https://ghcr.io/token?service=ghcr.io&scope=repository:bbartling/${image}:pull" | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")"
  curl -fsSL -H "Authorization: Bearer ${token}" -H "Accept: application/vnd.oci.image.index.v1+json" \
    "https://ghcr.io/v2/bbartling/${image}/manifests/${TAG}" \
    | python3 -c "import json,sys; m=json.load(sys.stdin); plats=[p.get('platform',{}) for p in m.get('manifests',[])]; print('${image}:${TAG}', plats); assert any(p.get('architecture')=='arm64' and p.get('os')=='linux' for p in plats), 'missing linux/arm64'"
}

for img in openfdd-bridge openfdd-commission openfdd-mcp-rag; do
  verify "$img"
done
echo "OK: linux/arm64 manifests present for ${TAG}"
