#!/usr/bin/env bash
# Soft-OPEN 370 T6a — published-candidate local qualification on one host profile.
#
# Profiles:
#   bench32-4g / bench32-8g     — 32 GB host sequential central caps
#   mintbench-3g                — ≤3 GiB combined (required first on mintbench)
#   mintbench-4g-central        — 4 GiB central only if fit; NEVER 8 GiB
#
# Usage (after GHCR tip publish):
#   OPENFDD_IMAGE_TAG=sha-<7> ./scripts/ops/run_t6a_local_qual.sh bench32-4g
#   OPENFDD_IMAGE_TAG=sha-<7> ./scripts/ops/run_t6a_local_qual.sh mintbench-3g
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROFILE="${1:-}"
[[ -n "$PROFILE" ]] || { echo "usage: $0 <profile>" >&2; exit 2; }
shift || true

case "$PROFILE" in
  bench32-4g) CENTRAL_MEM=4g; COMBINED_NOTE="bench32 4 GiB central" ;;
  bench32-8g) CENTRAL_MEM=8g; COMBINED_NOTE="bench32 8 GiB central" ;;
  mintbench-3g) CENTRAL_MEM=2g; COMBINED_NOTE="mintbench ≤3 GiB combined" ;;
  mintbench-4g-central) CENTRAL_MEM=4g; COMBINED_NOTE="mintbench 4 GiB central (fit required)" ;;
  *) echo "unknown profile: $PROFILE" >&2; exit 2 ;;
esac

if [[ "$PROFILE" == mintbench-* && "$CENTRAL_MEM" == "8g" ]]; then
  echo "FAIL: never 8 GiB central on mintbench" >&2
  exit 2
fi

TAG="${OPENFDD_IMAGE_TAG:-}"
if [[ -z "$TAG" ]]; then
  echo "ERROR: set OPENFDD_IMAGE_TAG=sha-<7> from ghcr_newest_by_created.py" >&2
  exit 2
fi

OUT="${OPENFDD_T6A_OUT:-$ROOT/reports/local_memory_bench/t6a_${PROFILE}_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$OUT"
echo "T6a profile=$PROFILE central_mem=$CENTRAL_MEM tag=$TAG out=$OUT ($COMBINED_NOTE)"

# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

export OPENFDD_IMAGE_TAG="$TAG"
export OPENFDD_CADDY="${OPENFDD_CADDY:-0}"
export OPENFDD_CENTRAL_BIND="${OPENFDD_CENTRAL_BIND:-127.0.0.1}"

# Preflight harness (fit + fixture hashes + docker/cgroup)
python3 "$ROOT/scripts/ops/local_memory_ingest_bench.py" \
  --profile "$PROFILE" \
  --phases preflight,fixture_hashes \
  --out "$OUT/preflight" | tee "$OUT/preflight.json"

# Pull + up csv recipe (central+web) — no local build
"$ROOT/scripts/openfdd_stack_pull.sh" csv
"$ROOT/scripts/openfdd_stack_up.sh" csv --no-pull

# Enforce central memory after recreate (compose may not ship mem_limit)
CENTRAL_CID="$(docker ps --filter name=openfdd-central --format '{{.ID}}' | head -1)"
if [[ -z "$CENTRAL_CID" ]]; then
  CENTRAL_CID="$(docker ps --format '{{.Names}}\t{{.ID}}' | awk '/central/{print $2; exit}')"
fi
if [[ -z "$CENTRAL_CID" ]]; then
  echo "FAIL: openfdd-central container not found" | tee "$OUT/FAIL.txt"
  exit 2
fi
docker update --memory="$CENTRAL_MEM" --memory-swap="$CENTRAL_MEM" "$CENTRAL_CID"
docker inspect "$CENTRAL_CID" --format 'central_memory={{.HostConfig.Memory}} name={{.Name}}' | tee "$OUT/central_cgroup.txt"

# Wait health
BASE="${OPENFDD_CENTRAL_BASE:-http://127.0.0.1:8080}"
for i in $(seq 1 60); do
  code=$(curl -s -o /tmp/t6a_health.json -w '%{http_code}' --connect-timeout 2 "$BASE/api/health" || echo 000)
  [[ "$code" == "200" ]] && break
  sleep 2
done
python3 - <<'PY' "$OUT" "$BASE"
import json,sys,urllib.request
out, base = sys.argv[1], sys.argv[2]
raw=urllib.request.urlopen(base+"/api/health", timeout=30).read()
h=json.loads(raw)
Path= __import__('pathlib').Path
Path(out,"health.json").write_text(json.dumps(h,indent=2)+"\n")
print("health_version", h.get("version"))
mb=h.get("memory_budget") or {}
print("peak", mb.get("peak_bytes"), "sample_ms", mb.get("sample_ms"), "source", mb.get("source"))
ver=str(h.get("version") or "")
if "3.5.71" not in ver:
    print("FAIL: expected 3.5.71 in health version, got", ver)
    raise SystemExit(2)
PY

# Live control phases
: "${OPENFDD_AGENT_PASSWORD:?OPENFDD_AGENT_PASSWORD required}"
python3 "$ROOT/scripts/ops/local_memory_ingest_bench.py" \
  --profile "$PROFILE" \
  --central-base "$BASE" \
  --phases health_schema,seed_append \
  --out "$OUT/live" \
  --fixture-root "${OPENFDD_BENCH_FIXTURE_ROOT:-/home/ben/Documents/buildings100_and_50}" \
  | tee "$OUT/live.json"

echo "T6a phase artifacts under $OUT"
python3 - <<'PY' "$OUT"
import json,sys
from pathlib import Path
out=Path(sys.argv[1])
verdicts=[]
for p in out.glob("*/SUMMARY.json"):
    d=json.loads(p.read_text())
    verdicts.append((str(p), d.get("verdict")))
    print(p.name, d.get("verdict"))
if any(v=="FAIL" for _,v in verdicts):
    raise SystemExit(2)
print("T6a_CONTROL_DONE")
PY
