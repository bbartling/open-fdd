#!/usr/bin/env bash
# Wave C entrypoint — run isolated 3.3.30 / 3.3.31 / 3.3.32 suites sequentially (dove-friendly).
# Requires OPENFDD_IMAGE_TAG=sha-<7>. Tears down leftovers after each suite.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TAG="${OPENFDD_IMAGE_TAG:?set OPENFDD_IMAGE_TAG to an immutable sha-<7> tag}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${ARTIFACT_DIR:-$ROOT/reports/waveC_isolated_${STAMP}}"
mkdir -p "$OUT"

export OPENFDD_IMAGE_TAG="$TAG"

run_one() {
  local name="$1" script="$2"
  local art="$OUT/$name"
  mkdir -p "$art"
  echo "======== $name ========"
  ARTIFACT_DIR="$art" bash "$script"
}

# Order: lightest MQTT broker → central restore → ZAP (pulls scanner).
run_one mqtts_isolation "$ROOT/scripts/integration/mqtts_transport_isolation.sh"
run_one restore_empty "$ROOT/scripts/qualification/restore_to_empty.sh"
run_one zap_af "$ROOT/scripts/qualification/run_isolated_zap_af.sh"

jq -n \
  --arg tag "$TAG" \
  --arg out "$OUT" \
  --slurpfile m "$OUT/mqtts_isolation/verdict.json" \
  --slurpfile r "$OUT/restore_empty/verdict.json" \
  --slurpfile z "$OUT/zap_af/verdict.json" \
  '{
    suite: "wave_c_isolated_v1",
    image_tag: $tag,
    artifact_dir: $out,
    pass: ($m[0].pass and $r[0].pass and $z[0].pass),
    children: { mqtts: $m[0], restore: $r[0], zap_af: $z[0] }
  }' | tee "$OUT/verdict.json"

echo "PASS: Wave C isolated suites → $OUT"
