#!/usr/bin/env bash
# Wave C entrypoint — isolated suites against the `cloud_portal` deployment
# profile, sequentially (dove-friendly): portal qualification (two tenants,
# NF emulator, security harness), restore-to-empty, then authenticated ZAP AF.
# Requires OPENFDD_IMAGE_TAG=sha-<7>. Each suite owns a unique compose project
# and tears down only that project. No MQTT broker, fieldbus, or OT listener.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TAG="${OPENFDD_IMAGE_TAG:?set OPENFDD_IMAGE_TAG to an immutable sha-<7> tag}"
if [[ ! "$TAG" =~ ^sha-[0-9a-f]{7}$ ]]; then
  echo "OPENFDD_IMAGE_TAG must match sha-<7 lowercase hex>, got: $TAG" >&2
  exit 1
fi
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${ARTIFACT_DIR:-$ROOT/reports/waveC_isolated_${STAMP}}"
mkdir -p "$OUT"
chmod 700 "$OUT"

export OPENFDD_IMAGE_TAG="$TAG"

SUITES=(portal_qual restore_empty zap_af)
declare -A SCRIPT=(
  [portal_qual]="$ROOT/scripts/qualification/run_portal_qualification.sh"
  [restore_empty]="$ROOT/scripts/qualification/restore_to_empty.sh"
  [zap_af]="$ROOT/scripts/qualification/run_isolated_zap_af.sh"
)
declare -A RC=()

for name in "${SUITES[@]}"; do
  art="$OUT/$name"
  mkdir -p "$art"
  echo "======== $name ========"
  set +e
  ARTIFACT_DIR="$art" bash "${SCRIPT[$name]}"
  RC[$name]=$?
  set -e
done

# A suite that died before writing a verdict counts as a failure.
child() {
  local f="$OUT/$1/verdict.json"
  if [[ -s "$f" ]] && jq -e . "$f" >/dev/null 2>&1; then
    jq -c --argjson rc "${RC[$1]}" '. + {exit_code: $rc}' "$f"
  else
    jq -cn --argjson rc "${RC[$1]}" '{pass: false, status: "ERROR", exit_code: $rc, detail: "no verdict.json"}'
  fi
}

jq -n \
  --arg tag "$TAG" \
  --arg out "$OUT" \
  --argjson p "$(child portal_qual)" \
  --argjson r "$(child restore_empty)" \
  --argjson z "$(child zap_af)" \
  'def ok: (.exit_code == 0) and ((.pass == true) or (.status == "PASS"));
  {
    suite: "wave_c_isolated_v2",
    deployment_profile: "cloud_portal",
    image_tag: $tag,
    artifact_dir: $out,
    pass: (($p | ok) and ($r | ok) and ($z | ok)),
    children: { portal_qualification: $p, restore: $r, zap_af: $z }
  }' | tee "$OUT/verdict.json"

if jq -e '.pass' "$OUT/verdict.json" >/dev/null; then
  echo "PASS: Wave C isolated suites (cloud_portal) → $OUT"
else
  echo "FAIL: Wave C isolated suites (cloud_portal) → $OUT" >&2
  exit 1
fi
