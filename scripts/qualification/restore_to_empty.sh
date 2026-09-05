#!/usr/bin/env bash
# 3.3.32 — True backup → empty disposable volume restore (+ tiny bounded API timing).
# Pulls openfdd-central from GHCR. Never touches live Railway /workspace.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TAG="${OPENFDD_IMAGE_TAG:?set OPENFDD_IMAGE_TAG to an immutable sha-<7> tag}"
if [[ ! "$TAG" =~ ^sha-[0-9a-f]{7}$ ]]; then
  echo "OPENFDD_IMAGE_TAG must match sha-<7 lowercase hex>, got: $TAG" >&2
  exit 1
fi

for cmd in docker curl jq; do
  command -v "$cmd" >/dev/null || { echo "missing required command: $cmd" >&2; exit 1; }
done
docker info >/dev/null

ART="${ARTIFACT_DIR:-$ROOT/reports/waveC_restore_empty_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
CENTRAL_IMAGE="ghcr.io/bbartling/openfdd-central:${TAG}"
PROJECT="openfdd-restore-empty-${RANDOM}"
VOL="${PROJECT}-workspace"
CTR="${PROJECT}-central"
ADMIN_PASS="restore-empty-admin-${RANDOM}"
JWT_SECRET="restore-empty-jwt-${RANDOM}"
PORT="$((18000 + RANDOM % 1000))"

cleanup() {
  docker rm -f "$CTR" >/dev/null 2>&1 || true
  docker volume rm -f "$VOL" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== Pull central $TAG =="
docker pull "$CENTRAL_IMAGE" >/dev/null
docker volume create "$VOL" >/dev/null

start_central() {
  docker rm -f "$CTR" >/dev/null 2>&1 || true
  docker run -d --name "$CTR" \
    -p "127.0.0.1:${PORT}:8080" \
    -e OPENFDD_MQTT_ENABLED=0 \
    -e OPENFDD_WORKSPACE=/workspace \
    -e OPENFDD_STORAGE_URL=file:///workspace/openfdd \
    -e OPENFDD_JWT_SECRET="$JWT_SECRET" \
    -e OPENFDD_ADMIN_PASSWORD="$ADMIN_PASS" \
    -e OPENFDD_ALLOW_OPEN_BIND=1 \
    -e OPENFDD_REACT_UI=1 \
    -v "${VOL}:/workspace" \
    "$CENTRAL_IMAGE" >/dev/null
  local deadline=$((SECONDS + 120))
  until curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "FAIL: central health timeout" >&2
      docker logs "$CTR" >&2 || true
      exit 1
    fi
    sleep 2
  done
}

echo "== Seed disposable volume =="
start_central
TOKEN="$(curl -fsS -X POST "http://127.0.0.1:${PORT}/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"${ADMIN_PASS}\"}" \
  | jq -r '.token // .access_token // empty')"
[[ -n "$TOKEN" ]]

FIXTURE="$ROOT/services/central/tests/fixtures/fc1_duct_static.csv"
test -f "$FIXTURE"
PREV="$(curl -fsS -X POST "http://127.0.0.1:${PORT}/api/csv/import/preview" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@${FIXTURE}")"
echo "$PREV" | jq -e '.ok == true and (.session_id | length > 0)' >/dev/null
SID="$(echo "$PREV" | jq -r '.session_id')"
# Best-effort commit if API supports it; seed marker always written into volume.
curl -fsS -X POST "http://127.0.0.1:${PORT}/api/csv/import/commit" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"session_id\":\"${SID}\"}" >"$ART/import_commit.json" 2>/dev/null || true

docker exec "$CTR" sh -lc '
  mkdir -p /workspace/openfdd/state /workspace/openfdd/packages /workspace/openfdd/rules
  echo "waveC-restore-marker" > /workspace/openfdd/state/waveC_restore_marker.txt
  echo "{\"rules\":[\"iso\"]}" > /workspace/openfdd/rules/iso_marker.json
  echo "pkg" > /workspace/openfdd/packages/iso_pkg.marker
'
docker exec "$CTR" sh -lc 'test -s /workspace/openfdd/state/waveC_restore_marker.txt'
ok_seed=1
echo "OK seeded volume (csv session=$SID)" | tee "$ART/seed.txt"

echo "== Backup volume tarball =="
docker run --rm -v "${VOL}:/workspace:ro" -v "$ART:/out" alpine:3.20 \
  tar -C /workspace -czf /out/workspace-backup.tgz . >/dev/null
test -s "$ART/workspace-backup.tgz"
ls -la "$ART/workspace-backup.tgz" | tee "$ART/backup_size.txt"

echo "== Wipe volume (empty) =="
docker rm -f "$CTR" >/dev/null
docker volume rm -f "$VOL" >/dev/null
docker volume create "$VOL" >/dev/null
# Prove empty
empty_count="$(docker run --rm -v "${VOL}:/workspace" alpine:3.20 sh -lc 'find /workspace -type f | wc -l' | tr -d ' ')"
echo "empty_file_count=$empty_count" | tee "$ART/empty_count.txt"
[[ "$empty_count" == "0" ]]

echo "== Restore tarball onto empty volume =="
docker run --rm -v "${VOL}:/workspace" -v "$ART:/in:ro" alpine:3.20 \
  tar -C /workspace -xzf /in/workspace-backup.tgz >/dev/null

echo "== Boot central on restored volume =="
start_central
docker exec "$CTR" sh -lc '
  test -s /workspace/openfdd/state/waveC_restore_marker.txt &&
  test -s /workspace/openfdd/rules/iso_marker.json &&
  test -s /workspace/openfdd/packages/iso_pkg.marker
'
curl -fsS "http://127.0.0.1:${PORT}/api/health" | tee "$ART/health_after_restore.json" \
  | jq -e '.service == "openfdd-central"' >/dev/null
echo "OK restore-to-empty markers + health" | tee "$ART/restore_ok.txt"

echo "== Bounded concurrent API timings =="
BASELINE="$ROOT/scripts/qualification/fixtures/bounded_perf_baseline.json"
TIMINGS="$ART/bounded_perf_timings.jsonl"
: > "$TIMINGS"
AUTH=(-H "Authorization: Bearer $TOKEN")
# Re-login in case JWT from pre-wipe is irrelevant — fresh token after restore.
TOKEN="$(curl -fsS -X POST "http://127.0.0.1:${PORT}/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"${ADMIN_PASS}\"}" \
  | jq -r '.token // .access_token // empty')"
AUTH=(-H "Authorization: Bearer $TOKEN")

measure() {
  local path="$1"
  local i
  for i in $(seq 1 20); do
    local start end ms
    start="$(date +%s%N)"
    curl -fsS --max-time 5 "http://127.0.0.1:${PORT}${path}" "${AUTH[@]}" >/dev/null
    end="$(date +%s%N)"
    ms=$(( (end - start) / 1000000 ))
    echo "{\"path\":\"${path}\",\"ms\":${ms}}" >> "$TIMINGS"
  done
}

# Warm then measure health + authenticated datasets in parallel batches.
curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null
measure /api/health
measure /api/datasets

python3 - "$TIMINGS" "$BASELINE" "$ART/bounded_perf_verdict.json" <<'PY'
import json, statistics, sys
from pathlib import Path
timings_path, baseline_path, out_path = sys.argv[1:4]
rows = [json.loads(l) for l in Path(timings_path).read_text().splitlines() if l.strip()]
by = {}
for r in rows:
    by.setdefault(r["path"], []).append(r["ms"])
def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = int(round((p/100) * (len(xs)-1)))
    return xs[k]
summary = {}
for path, xs in by.items():
    summary[path] = {
        "n": len(xs),
        "p50_ms": pct(xs, 50),
        "p95_ms": pct(xs, 95),
        "max_ms": max(xs),
    }
baseline = json.loads(Path(baseline_path).read_text())
ok = True
checks = {}
for path, budget in baseline.get("budgets_ms", {}).items():
    got = summary.get(path)
    if not got:
        checks[path] = {"ok": False, "reason": "missing"}
        ok = False
        continue
    p50_ok = got["p50_ms"] <= budget["p50"]
    p95_ok = got["p95_ms"] <= budget["p95"]
    checks[path] = {"ok": p50_ok and p95_ok, "got": got, "budget": budget}
    ok = ok and p50_ok and p95_ok
verdict = {"suite": "bounded_perf_v1", "pass": ok, "summary": summary, "checks": checks}
Path(out_path).write_text(json.dumps(verdict, indent=2) + "\n")
print(json.dumps(verdict, indent=2))
sys.exit(0 if ok else 1)
PY
PERF_RC=$?

jq -n \
  --arg tag "$TAG" \
  --arg art "$ART" \
  --argjson seed "$ok_seed" \
  --argjson perf_ok "$([[ $PERF_RC -eq 0 ]] && echo true || echo false)" \
  '{
    suite: "restore_to_empty_v1",
    image_tag: $tag,
    artifact_dir: $art,
    pass: ($seed == 1 and $perf_ok),
    restore_to_empty: true,
    bounded_perf_pass: $perf_ok,
    notes: "Never restore over live Railway workspace."
  }' | tee "$ART/verdict.json"

if [[ "$PERF_RC" != "0" ]]; then
  echo "FAIL: bounded perf budgets" >&2
  exit 1
fi
echo "PASS: restore-to-empty + bounded perf → $ART"
