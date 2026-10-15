#!/usr/bin/env bash
# Local cgroup-limited OOM / memory-stress regression (#1179 / gates 37+38 shape).
# Gate47 evaluator: existence of a zero-byte artifact is NOT a PASS.
#
# Requires ALL of:
#   1) Successful analytics/runtime workload (HTTP success + nonempty typed JSON)
#   2) Separate induced-pressure / cancel-drain proof (AFDD run-now + status)
#   3) Process alive, started_at stable, raw cgroup memory.peak under shed fraction
#
# Synthetic evaluator smoke ≠ successful memory stress.
#
# Usage (GHCR tip already pulled; never local docker build on bensbench):
#   OPENFDD_IMAGE_TAG=sha-<7> ./scripts/gates/afdd_oom_regression.sh
#
# Env:
#   OPENFDD_OOM_MEMORY_GB     container hard limit (default 6)
#   OPENFDD_OOM_SHED_FRACTION peak must be < this × limit (default 0.75)
#   OPENFDD_OOM_HIVE_ROOT     host path mounted as /workspace/openfdd
#   OPENFDD_IMAGE_TAG         ghcr tip (required)
#   OPENFDD_DATABASE_URL      optional Timescale URL (preferred; Parquet retired)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MEM_GB="${OPENFDD_OOM_MEMORY_GB:-6}"
SHED_FRAC="${OPENFDD_OOM_SHED_FRACTION:-0.75}"
TAG="${OPENFDD_IMAGE_TAG:-}"
HIVE="${OPENFDD_OOM_HIVE_ROOT:-}"
ART="${ARTIFACT_DIR:-$ROOT/reports/afdd_oom_regression_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
export ART

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

DOCKER_ENV=(
  -e OPENFDD_STORAGE_URL="file:///workspace/openfdd"
  -e OPENFDD_JWT_SECRET="oom-regression-secret-at-least-32b"
  -e OPENFDD_ADMIN_PASSWORD="oom-regression-admin"
)
if [[ -n "${OPENFDD_DATABASE_URL:-}" ]]; then
  DOCKER_ENV+=(-e "OPENFDD_DATABASE_URL=${OPENFDD_DATABASE_URL}")
  echo "historian=timescale (OPENFDD_DATABASE_URL set)" | tee -a "$ART/run.txt"
else
  # Legacy hive path for pre-Timescale tip images only; Timescale is product.
  DOCKER_ENV+=(
    -e OPENFDD_PARQUET_ROOT="/workspace/openfdd"
    -e OPENFDD_DATAFUSION_SPILL_DIR="/workspace/openfdd/.datafusion-spill"
  )
  echo "NOTE: OPENFDD_DATABASE_URL unset — tip may refuse Parquet; prefer Timescale URL" \
    | tee -a "$ART/run.txt"
fi

docker pull "$IMG" >/dev/null
docker run -d --name "$NAME" \
  --memory="${MEM_GB}g" --memory-swap="${MEM_GB}g" \
  "${DOCKER_ENV[@]}" \
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
if [[ -z "$TOKEN" ]]; then
  echo "FAIL: login returned empty token" | tee "$ART/FAIL.txt"
  exit 1
fi

# ---------------------------------------------------------------------------
# Gate47 / Gate-37: successful workload execution + nonempty typed output.
# curl failure or zero-byte/empty JSON is FAIL (not "fail-closed ok" PASS).
# ---------------------------------------------------------------------------
set +e
curl -fsS -X POST "http://127.0.0.1:18080/api/analytics/runtime" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"building_id":"ACME","refresh":true}' \
  >"$ART/runtime.json"
RUNTIME_HTTP=$?
set -e
echo "runtime_http=$RUNTIME_HTTP runtime_bytes=$(wc -c <"$ART/runtime.json" | tr -d ' ')" \
  | tee -a "$ART/run.txt"
python3 "$ROOT/scripts/gates/gate47_eval_artifacts.py" workload \
  --path "$ART/runtime.json" --http "$RUNTIME_HTTP" \
  --pass-file "$ART/workload_PASS.txt" \
  | tee -a "$ART/run.txt" \
  || { echo "FAIL: Gate47 runtime workload/typed output" | tee "$ART/FAIL.txt"; exit 1; }
# ---------------------------------------------------------------------------
# Separate induced-pressure / cancel-drain proof (Gate-38 shape).
# Must actually exercise the scheduler path; empty artifact ≠ PASS.
# ---------------------------------------------------------------------------
set +e
curl -fsS --max-time 120 -X POST "http://127.0.0.1:18080/api/afdd/scheduler/run-now" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"building_id":"ACME"}' \
  >"$ART/run_now.json"
PRESSURE_HTTP=$?
set -e
echo "run_now_http=$PRESSURE_HTTP run_now_bytes=$(wc -c <"$ART/run_now.json" | tr -d ' ')" \
  | tee -a "$ART/run.txt"
export PRESSURE_HTTP

# Cancel/drain probe: status must remain reachable after pressure (drain proof).
set +e
curl -fsS --max-time 30 "http://127.0.0.1:18080/api/afdd/scheduler/status" \
  -H "Authorization: Bearer $TOKEN" \
  >"$ART/scheduler_status.json"
STATUS_HTTP=$?
set -e
echo "scheduler_status_http=$STATUS_HTTP status_bytes=$(wc -c <"$ART/scheduler_status.json" | tr -d ' ')" \
  | tee -a "$ART/run.txt"
python3 "$ROOT/scripts/gates/gate47_eval_artifacts.py" pressure \
  --run-now "$ART/run_now.json" --status "$ART/scheduler_status.json" \
  --run-http "$PRESSURE_HTTP" --status-http "$STATUS_HTTP" \
  --pass-file "$ART/pressure_PASS.txt" \
  | tee -a "$ART/run.txt" \
  || { echo "FAIL: Gate47 induced-pressure/cancel-drain" | tee "$ART/FAIL.txt"; exit 1; }
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
import os, sys
mem_gb = float("${MEM_GB}")
shed = float("${SHED_FRAC}")
limit = int(mem_gb * 1024**3)
peak_raw = """${PEAK}""".strip()
if not peak_raw.isdigit():
    print("BLOCKED: memory.peak not an integer:", peak_raw)
    sys.exit(2)
peak = int(peak_raw)
art = "${ART}"
open(os.path.join(art, "peak.txt"), "w").write(peak_raw + "\n")
cap = int(limit * shed)
print(f"memory.peak={peak} limit={limit} shed_cap={cap}")
if peak >= cap:
    print(f"FAIL: peak {peak} >= shed fraction cap {cap}")
    sys.exit(1)
# Final Gate47 composite: workload + pressure proofs must already exist.
for name in ("workload_PASS.txt", "pressure_PASS.txt"):
    p = os.path.join(art, name)
    if not os.path.isfile(p) or os.path.getsize(p) == 0:
        print(f"FAIL: missing {name} — memory peak alone is not memory-stress PASS")
        sys.exit(1)
print(
    "PASS: Gate47 memory stress — workload ok, pressure/cancel-drain ok, "
    "process alive, started_at stable, raw cgroup peak under shed fraction"
)
PY
rc=$?
curl -fsS http://127.0.0.1:18080/api/health >"$ART/health_after.json" || true
exit "$rc"
