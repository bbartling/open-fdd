#!/usr/bin/env bash
# Astra C-ZAP (A06–A07) — disposable authenticated ZAP AF wrapper.
#
# Mints a throwaway web+central candidate from GHCR, then delegates scan
# evaluation to scripts/qualification/zap/run_af_disposable.py (single
# evaluator). Compatibility entrypoint for Wave C / gate runners.
#
# Never activeScans live Railway OT. Never persists JWT to disk.
# No fallback crawl or warning soft-pass paths.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TAG="${OPENFDD_IMAGE_TAG:?set OPENFDD_IMAGE_TAG to an immutable sha-<7> tag}"
if [[ ! "$TAG" =~ ^sha-[0-9a-f]{7}$ ]]; then
  echo "OPENFDD_IMAGE_TAG must match sha-<7 lowercase hex>, got: $TAG" >&2
  exit 1
fi

for cmd in docker curl jq python3; do
  command -v "$cmd" >/dev/null || { echo "missing required command: $cmd" >&2; exit 1; }
done
docker info >/dev/null

# Pin scanner digest (override only with another digest-pinned ref).
ZAP_IMAGE="${OPENFDD_ZAP_IMAGE:-ghcr.io/zaproxy/zaproxy@sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef}"
if [[ "$ZAP_IMAGE" != *@sha256:* ]]; then
  echo "FAIL: OPENFDD_ZAP_IMAGE must be digest-pinned (@sha256:…); got: $ZAP_IMAGE" >&2
  exit 1
fi
CENTRAL_IMAGE="ghcr.io/bbartling/openfdd-central:${TAG}"
WEB_IMAGE="ghcr.io/bbartling/openfdd-web:${TAG}"
ART="${ARTIFACT_DIR:-$ROOT/reports/waveC_zap_af_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
WRK="$ART/zap_wrk"
mkdir -p "$WRK"
# Restrict artifact tree (no JWT on disk). ZAP image often runs as uid 1000 —
# make wrk world-accessible for the mount only (plan/report; never secrets).
chmod 700 "$ART"
chmod 777 "$WRK"
cp "$ROOT/docs/openapi.yaml" "$WRK/openapi.yaml"

NET="openfdd-zap-af-${RANDOM}"
CTR_CENTRAL="openfdd-zap-central-${RANDOM}"
CTR_WEB="openfdd-zap-web-${RANDOM}"
VOL="${CTR_CENTRAL}-workspace"
ADMIN_PASS="zap-af-admin-${RANDOM}"
JWT_SECRET="zap-af-jwt-${RANDOM}"
# A07: scan through nginx+SPA (web), not bare central.
TARGET_ORIGIN="http://web:8080"

cleanup() {
  docker rm -f "$CTR_WEB" "$CTR_CENTRAL" >/dev/null 2>&1 || true
  docker volume rm -f "$VOL" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== Pull images =="
docker pull "$CENTRAL_IMAGE" >/dev/null
docker pull "$WEB_IMAGE" >/dev/null
docker pull "$ZAP_IMAGE" >/dev/null

docker network create "$NET" >/dev/null
docker volume create "$VOL" >/dev/null

docker run -d --name "$CTR_CENTRAL" --network "$NET" --network-alias central \
  -e OPENFDD_MQTT_ENABLED=0 \
  -e OPENFDD_WORKSPACE=/workspace \
  -e OPENFDD_STORAGE_URL=file:///workspace/openfdd \
  -e OPENFDD_JWT_SECRET="$JWT_SECRET" \
  -e OPENFDD_ADMIN_PASSWORD="$ADMIN_PASS" \
  -e OPENFDD_ALLOW_OPEN_BIND=1 \
  -e OPENFDD_REACT_UI=1 \
  -e OPENFDD_MULTI_TENANT="${OPENFDD_MULTI_TENANT:-0}" \
  -v "${VOL}:/workspace" \
  "$CENTRAL_IMAGE" >/dev/null

# Wave N: optional MT-ON candidate seeds control plane before health wait.
if [[ "${OPENFDD_MULTI_TENANT:-0}" == "1" || "${OPENFDD_MULTI_TENANT:-0}" == "true" ]]; then
  docker run --rm -v "${VOL}:/workspace" alpine:3.20 \
    sh -c 'mkdir -p /workspace/openfdd/control_plane && cat > /workspace/openfdd/control_plane/tenants.json <<EOF
{"tenants":[
  {"id":"acme","name":"ACME","building_ids":["ACME"]},
  {"id":"building_100","name":"Building 100","building_ids":["BUILDING_100"]},
  {"id":"lakeside_sd","name":"Lakeside SD","building_ids":["LAKESIDE_ES"]}
]}
EOF'
fi

docker run -d --name "$CTR_WEB" --network "$NET" --network-alias web \
  -e OPENFDD_CENTRAL_UPSTREAM=central:8080 \
  -e OPENFDD_NGINX_RESOLVER=127.0.0.11 \
  "$WEB_IMAGE" >/dev/null

deadline=$((SECONDS + 120))
until docker run --rm --network "$NET" curlimages/curl:8.5.0 \
    -fsS "${TARGET_ORIGIN}/api/health" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "FAIL: disposable web+central never healthy" >&2
    docker logs "$CTR_CENTRAL" >&2 || true
    docker logs "$CTR_WEB" >&2 || true
    exit 1
  fi
  sleep 2
done
echo "OK disposable web+central"

TOKEN="$(docker run --rm --network "$NET" curlimages/curl:8.5.0 -fsS \
  -X POST "${TARGET_ORIGIN}/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"${ADMIN_PASS}\"}" \
  | jq -r '.token // .access_token // empty')"
if [[ -z "$TOKEN" ]]; then
  echo "FAIL: could not mint admin JWT for ZAP context" >&2
  exit 1
fi
# UA-04: never persist JWT to artifact disk (env injection only).
rm -f "$ART/admin.jwt" "$WRK/admin.jwt" 2>/dev/null || true
echo "OK admin JWT minted (ephemeral env only)"

# Copy OpenAPI into work dir for AF openapi job (served via central too).
# Evaluator owns AF plan materialization + verdict; wrapper only mints candidate.
export OPENFDD_ZAP_AF_EXECUTE=1
export OPENFDD_ZAP_IMAGE="$ZAP_IMAGE"
export OPENFDD_ZAP_REQUIRE_DIGEST=1
export ZAP_TARGET_ORIGIN="$TARGET_ORIGIN"
export ZAP_AUTH_HEADER_VALUE="Bearer ${TOKEN}"
export ZAP_AF_WORK_DIR="$WRK"
export ZAP_DOCKER_NETWORK="$NET"
export ZAP_AF_RUN_STARTED_EPOCH="$(date +%s)"
VERDICT_OUT="$ART/verdict.json"

set +e
python3 -B "$ROOT/scripts/qualification/zap/run_af_disposable.py" \
  --out "$VERDICT_OUT"
EVAL_RC=$?
set -e

# Redact any accidental secret leakage from logs copied beside verdict.
chmod -R u+rwX,g+rwX,o-rwx "$WRK" 2>/dev/null || true
rm -f "$ART/admin.jwt" "$WRK/admin.jwt" 2>/dev/null || true

if [[ ! -f "$VERDICT_OUT" ]]; then
  echo "FAIL: evaluator wrote no verdict" >&2
  exit 1
fi

# Surface evaluator summary without secrets.
python3 -B - "$VERDICT_OUT" <<'PY'
import json, sys
from pathlib import Path
v = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(
    f"evaluator status={v.get('status')} high={v.get('high_alerts')} "
    f"medium={v.get('medium_alerts')} notes={v.get('notes')}"
)
PY

if [[ "$EVAL_RC" -ne 0 ]]; then
  echo "FAIL: isolated ZAP AF suite (evaluator rc=$EVAL_RC)" >&2
  exit "$EVAL_RC"
fi
echo "PASS: isolated ZAP AF (web+central via run_af_disposable.py) → $ART"
