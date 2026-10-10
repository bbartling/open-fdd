#!/usr/bin/env bash
# Local cgroup-limited OOM regression for #1179 / gates 37+38 shape.
#
# Runs central under `docker run --memory=<N>g` against an ACME-shaped hive
# (or OPENFDD_OOM_HIVE_ROOT). Asserts process stays alive and cgroup
# memory.peak stays below shed fraction × limit.
#
# Usage (GHCR tip already pulled; never local docker build on bensbench):
#   OPENFDD_IMAGE_TAG=sha-<7> ./scripts/gates/afdd_oom_regression.sh
#
# Env:
#   OPENFDD_OOM_MEMORY_GB     container hard limit (default 6)
#   OPENFDD_OOM_SHED_FRACTION peak must be < this × limit (default 0.75)
#   OPENFDD_OOM_HIVE_ROOT     host path mounted as /workspace/openfdd
#   OPENFDD_IMAGE_TAG         ghcr tip (required)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MEM_GB="${OPENFDD_OOM_MEMORY_GB:-6}"
SHED_FRAC="${OPENFDD_OOM_SHED_FRACTION:-0.75}"
TAG="${OPENFDD_IMAGE_TAG:-}"
HIVE="${OPENFDD_OOM_HIVE_ROOT:-}"
ART="${ARTIFACT_DIR:-$ROOT/reports/afdd_oom_regression_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"

if [[ -z "$TAG" ]]; then
  echo "FAIL: set OPENFDD_IMAGE_TAG=sha-<7> (newest-by-created)" | tee "$ART/FAIL.txt"
  exit 2
fi
if [[ -z "$HIVE" || ! -d "$HIVE" ]]; then
  echo "BLOCKED: set OPENFDD_OOM_HIVE_ROOT to an ACME-shaped historian tree" | tee "$ART/BLOCKED.txt"
  exit 2
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "BLOCKED: docker not on PATH" | tee "$ART/BLOCKED.txt"
  exit 2
fi

IMG="ghcr.io/bbartling/openfdd-central:${TAG}"
NAME="openfdd-oom-reg-$$"
echo "oom regression image=$IMG memory=${MEM_GB}g shed_frac=$SHED_FRAC" | tee "$ART/run.txt"

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Writable workspace+spill overlay: seed from hive, never mount historian :ro
# (spill/import need write). JWT secret must be ≥32 chars (auth fail-closed).
WORK="$ART/workspace_overlay"
mkdir -p "$WORK"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete "$HIVE"/ "$WORK"/
else
  cp -a "$HIVE"/. "$WORK"/
fi
mkdir -p "$WORK/.datafusion-spill"

docker pull "$IMG" >/dev/null
docker run -d --name "$NAME" \
  --memory="${MEM_GB}g" --memory-swap="${MEM_GB}g" \
  -e OPENFDD_STORAGE_URL="file:///workspace/openfdd" \
  -e OPENFDD_PARQUET_ROOT="/workspace/openfdd" \
  -e OPENFDD_DATAFUSION_SPILL_DIR="/workspace/openfdd/.datafusion-spill" \
  -e OPENFDD_JWT_SECRET="oom-regression-secret-at-least-32b" \
  -e OPENFDD_ADMIN_PASSWORD="oom-regression-admin" \
  -v "$WORK:/workspace/openfdd:rw" \
  -p 18080:8080 \
  "$IMG" >/dev/null

# Wait health
ok=0
for _ in $(seq 1 60); do
  if curl -fsS --max-time 2 "http://127.0.0.1:18080/api/health" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 1
done
if [[ "$ok" != "1" ]]; then
  docker logs "$NAME" >"$ART/central.log" 2>&1 || true
  echo "FAIL: central never healthy" | tee "$ART/FAIL.txt"
  exit 1
fi
STARTED="$(curl -fsS http://127.0.0.1:18080/api/health | python3 -c 'import json,sys; print(json.load(sys.stdin).get("started_at",""))')"
echo "started_at=$STARTED" | tee -a "$ART/run.txt"

TOKEN="$(curl -fsS -X POST http://127.0.0.1:18080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"oom-regression-admin"}' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("token") or d.get("access_token") or "")')"

# Gate-37 shape: runtime envelope
curl -fsS -X POST "http://127.0.0.1:18080/api/analytics/runtime" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"building_id":"ACME","refresh":true}' \
  >"$ART/runtime.json" || echo "runtime HTTP non-zero (fail-closed ok)" | tee -a "$ART/run.txt"

# Gate-38 shape: AFDD run-now
curl -fsS -X POST "http://127.0.0.1:18080/api/afdd/scheduler/run-now" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"building_id":"ACME"}' \
  >"$ART/run_now.json" || echo "run-now HTTP non-zero (partial/cancelled ok)" | tee -a "$ART/run.txt"

# Process still alive?
if ! docker inspect -f '{{.State.Running}}' "$NAME" | grep -q true; then
  docker logs "$NAME" >"$ART/central.log" 2>&1 || true
  echo "FAIL: container not running after heavy work (likely OOM kill)" | tee "$ART/FAIL.txt"
  exit 1
fi
AFTER="$(curl -fsS http://127.0.0.1:18080/api/health | python3 -c 'import json,sys; print(json.load(sys.stdin).get("started_at",""))')"
if [[ "$AFTER" != "$STARTED" ]]; then
  echo "FAIL: started_at flipped $STARTED -> $AFTER" | tee "$ART/FAIL.txt"
  exit 1
fi

# memory.peak from cgroup only — never substitute current docker-stats as peak
# (M70-10). Unsupported peak = BLOCKED.
CG=$(docker inspect -f '{{.Id}}' "$NAME")
PEAK=""
PEAK_SRC=""
for p in \
  "/sys/fs/cgroup/system.slice/docker-${CG}.scope/memory.peak" \
  "/sys/fs/cgroup/docker/${CG}/memory.peak" \
  "/sys/fs/cgroup/memory/docker/${CG}/memory.peak"; do
  if [[ -r "$p" ]]; then PEAK="$(cat "$p")"; PEAK_SRC="$p"; break; fi
done
if [[ -z "$PEAK" ]]; then
  echo "BLOCKED: raw cgroup memory.peak unavailable (docker-stats current is not peak)" \
    | tee "$ART/BLOCKED.txt"
  exit 2
fi
echo "peak_source=$PEAK_SRC peak_raw=$PEAK" | tee -a "$ART/run.txt"
python3 - <<PY | tee -a "$ART/run.txt"
import sys
mem_gb = float("${MEM_GB}")
shed = float("${SHED_FRAC}")
limit = int(mem_gb * 1024**3)
peak_raw = """${PEAK}""".strip()
if not peak_raw.isdigit():
    print("BLOCKED: memory.peak not an integer:", peak_raw)
    sys.exit(2)
peak = int(peak_raw)
open("${ART}/peak.txt","w").write(peak_raw + "\n")
cap = int(limit * shed)
print(f"memory.peak={peak} limit={limit} shed_cap={cap}")
if peak >= cap:
    print(f"FAIL: peak {peak} >= shed fraction cap {cap}")
    sys.exit(1)
print("PASS: process alive, started_at stable, raw cgroup peak under shed fraction")
PY
rc=$?
curl -fsS http://127.0.0.1:18080/api/health >"$ART/health_after.json" || true
exit "$rc"
