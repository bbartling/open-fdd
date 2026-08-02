#!/usr/bin/env bash
# Pull immutable GHCR tip images (wait for publish), assert nightly↔sha digests,
# bring up react-ot. Builds openfdd-web locally when GHCR does not publish it yet.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
export ARTIFACT_DIR="$ART"

hdr "GHCR pull + pin + react-ot up"

# Resolve a *published* pin (wait/retry tip, else nightly OCI revision fallback).
if ! resolve_published_image_tag; then
  bad "could not resolve a published GHCR image pin"
  summary
  exit 1
fi

# Re-export image refs against the pin (ignore stale overrides from env).
unset OPENFDD_CENTRAL_IMAGE OPENFDD_FIELDBUS_IMAGE OPENFDD_MQTT_IMAGE OPENFDD_MCP_IMAGE OPENFDD_WEB_IMAGE
unset OPENFDD_UI_IMAGE || true
openfdd_stack_export_image_env

echo "${DIM}pin=$OPENFDD_IMAGE_TAG source=${PIN_SOURCE:-?} site/edge=${OPENFDD_SITE_ID}/${OPENFDD_EDGE_ID}${RST}"
{
  echo "$OPENFDD_IMAGE_TAG"
  echo "pin_source=${PIN_SOURCE:-unknown}"
} >"$ART/image_tag.txt"

# Images already pulled by resolve_published_image_tag; refresh refs for digest assert.
PULL_IMGS=(
  "$OPENFDD_CENTRAL_IMAGE"
  "$OPENFDD_FIELDBUS_IMAGE"
  "$OPENFDD_MQTT_IMAGE"
  "$OPENFDD_MCP_IMAGE"
)
for img in "${PULL_IMGS[@]}"; do
  echo "${DIM}ensure $img${RST}"
  docker pull "$img" >/dev/null
done

# Assert nightly currently points at the same digests (CHANNEL check)
hdr "nightly ↔ sha digest equality"
DIGESTS_FILE="$ART/digests.txt"
: >"$DIGESTS_FILE"
DIGEST_FAIL=0
for name in openfdd-central openfdd-fieldbus openfdd-mqtt openfdd-mcp; do
  sha_ref="ghcr.io/bbartling/${name}:${OPENFDD_IMAGE_TAG}"
  night_ref="ghcr.io/bbartling/${name}:nightly"
  docker pull "$night_ref" >/dev/null
  d_sha="$(image_digest "$sha_ref")"
  d_night="$(image_digest "$night_ref")"
  echo "${name} sha=${d_sha} nightly=${d_night}" | tee -a "$DIGESTS_FILE"
  if [[ -n "$d_sha" && "$d_sha" == "$d_night" ]]; then
    ok "$name nightly matches $OPENFDD_IMAGE_TAG"
  else
    bad "$name nightly≠sha (sha=$d_sha nightly=$d_night)"
    DIGEST_FAIL=1
  fi
done
if [[ "$DIGEST_FAIL" -ne 0 ]]; then
  summary
  exit 1
fi

# openfdd-web: pull if published, else mark for local build
if docker pull "$OPENFDD_WEB_IMAGE" 2>/dev/null; then
  ok "pulled $OPENFDD_WEB_IMAGE"
  echo "web=pulled" >"$ART/web_source.txt"
else
  skip "openfdd-web not in GHCR — will compose-build from frontend/web"
  echo "web=build-local" >"$ART/web_source.txt"
fi

mapfile -t CF < <(compose_files)
echo "${DIM}compose: ${CF[*]}${RST}"

# Preflight UDP 47808
if command -v ss >/dev/null; then
  if ss -ulnp 2>/dev/null | grep -q ':47808'; then
    echo "${DIM}UDP 47808 already bound (expect fieldbus after up)${RST}"
  fi
fi

mkdir -p "$ROOT/workspace" "$ROOT/deploy/mqtt/certs" "$ROOT/deploy/mqtt/kits"

export OPENFDD_SITE_ID OPENFDD_EDGE_ID
export OPENFDD_REACT_UI=1
export OPENFDD_UI_GENERATION_DEFAULT=react
export OPENFDD_IMAGE_TAG

# Bring up via stack helper (builds web when missing)
"$ROOT/scripts/openfdd_stack_up.sh" react-ot --no-pull

echo
docker compose "${CF[@]}" ps
echo
docker compose "${CF[@]}" images 2>/dev/null || true

{
  echo "Image revisions:"
  for s in fieldbus central mqtt web; do
    c="$(docker ps --format '{{.Names}}' | grep -E "openfdd-react-${s}" | head -1 || true)"
    if [[ -n "$c" ]]; then
      docker inspect "$c" --format "$s={{.Config.Image}} rev={{index .Config.Labels \"org.opencontainers.image.revision\"}}" 2>/dev/null || echo "$s=inspect-fail"
    else
      echo "$s=missing"
    fi
  done
  docker inspect "$OPENFDD_MCP_IMAGE" --format 'mcp={{.Config.Image}} rev={{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null || echo "mcp=missing"
} | tee "$ART/image_revs.txt"

# Wait for container healthchecks so 01 doesn't race a still-starting stack
echo "${DIM}waiting up to 120s for container health...${RST}"
deadline=$((SECONDS + 120))
while ((SECONDS < deadline)); do
  starting="$(docker compose "${CF[@]}" ps --format json 2>/dev/null \
    | jq -r 'select(.Health=="starting" or .State=="restarting") | .Name' | wc -l)"
  [[ "$starting" -eq 0 ]] && break
  sleep 5
done
docker compose "${CF[@]}" ps --format '{{.Name}} {{.Status}}' 2>/dev/null || true

# Fieldbus is host-net — wait on HTTP
fb_deadline=$((SECONDS + 60))
while ((SECONDS < fb_deadline)); do
  curl -fsS --max-time 3 "$FIELDBUS_BASE/health" >/dev/null 2>&1 && break
  sleep 2
done

ok "compose up issued (verify health with 01_health_gates.sh)"
summary
