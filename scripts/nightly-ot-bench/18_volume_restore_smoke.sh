#!/usr/bin/env bash
# Gate 18 — volume restore smoke after image re-pin (patch cycle).
# Proves CSV packages, MQTT-streamed historian Parquet, and ingest state survive
# container recreate when workspace/ (local) or Railway /workspace volume is kept.
# Does NOT test tarball disaster recovery — see docs/operations/backup-update-restore.md.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
auth_setup
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"

hdr "Volume restore smoke (patch-cycle re-pin)"

central_auth_setup

baseline() {
  local tag="$1"
  curl -fsS --max-time 20 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
    "$CENTRAL_BASE/api/health" >"$ART/health_${tag}.json" 2>/dev/null || echo '{}' >"$ART/health_${tag}.json"
  curl -fsS --max-time 20 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
    "$CENTRAL_BASE/api/ingest/stats" >"$ART/ingest_${tag}.json" 2>/dev/null || echo '{}' >"$ART/ingest_${tag}.json"
  curl -fsS --max-time 20 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
    "$CENTRAL_BASE/api/fdd/cache/status" >"$ART/fdd_cache_${tag}.json" 2>/dev/null || echo '{}' >"$ART/fdd_cache_${tag}.json"
  curl -fsS --max-time 20 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
    "$CENTRAL_BASE/api/datasets" >"$ART/datasets_${tag}.json" 2>/dev/null || echo '{}' >"$ART/datasets_${tag}.json"
  historian_snapshot >"$ART/historian_${tag}.txt" 2>/dev/null || : >"$ART/historian_${tag}.txt"
  find "$ROOT/workspace/openfdd" -name 'manifest.json' -maxdepth 1 -exec cat {} \; \
    >"$ART/parquet_manifest_${tag}.json" 2>/dev/null || echo '{}' >"$ART/parquet_manifest_${tag}.json"
  wc -l <"$ART/historian_${tag}.txt" | tr -d ' ' >"$ART/historian_count_${tag}.txt"
}

hdr "Baseline (before central recreate)"
baseline before

PQ_BEFORE="$(jq -r '.parquet_file_count // 0' "$ART/fdd_cache_before.json" 2>/dev/null || echo 0)"
INGEST_BEFORE="$(jq -r '.ingest_ok // 0' "$ART/health_before.json" 2>/dev/null || echo 0)"
DATASETS_BEFORE="$(jq -r '(.datasets // .records // []) | length' "$ART/datasets_before.json" 2>/dev/null || echo 0)"
HIST_BEFORE="$(cat "$ART/historian_count_before.txt")"

if [[ "$PQ_BEFORE" =~ ^[0-9]+$ ]] && [[ "$PQ_BEFORE" -gt 0 ]]; then
  ok "baseline parquet_file_count=$PQ_BEFORE"
else
  bad "baseline parquet cache empty — import CSV or run MQTT soak first"
  summary
  exit 1
fi
ok "baseline ingest_ok=$INGEST_BEFORE datasets=$DATASETS_BEFORE historian_files=$HIST_BEFORE"

hdr "Simulate patch re-pin — force-recreate central (same workspace bind mount)"
CTR="$(docker ps --format '{{.Names}}' | grep -E 'openfdd-react-central' | head -1 || true)"
if [[ -z "$CTR" ]]; then
  bad "openfdd-react-central container not running"
  summary
  exit 1
fi
COMPOSE_FILES="-f docker/compose.react.yml -f docker/compose.react.fieldbus.yml"
if [[ -f docker/compose.caddy.react.yml ]] && docker ps --format '{{.Names}}' | grep -q openfdd-react-caddy; then
  COMPOSE_FILES="$COMPOSE_FILES -f docker/compose.caddy.react.yml"
fi
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES up -d --no-deps --force-recreate central 2>&1 | tee "$ART/central_recreate.log"
sleep 5
for _ in $(seq 1 30); do
  if curl -fsS --max-time 3 "$CENTRAL_BASE/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
if ! curl -fsS --max-time 10 "$CENTRAL_BASE/api/health" >/dev/null 2>&1; then
  bad "central unhealthy after recreate"
  summary
  exit 1
fi
ok "central recreated and /api/health reachable"

hdr "Post-recreate verification"
baseline after

PQ_AFTER="$(jq -r '.parquet_file_count // 0' "$ART/fdd_cache_after.json" 2>/dev/null || echo 0)"
INGEST_AFTER="$(jq -r '.ingest_ok // 0' "$ART/health_after.json" 2>/dev/null || echo 0)"
DATASETS_AFTER="$(jq -r '(.datasets // .records // []) | length' "$ART/datasets_after.json" 2>/dev/null || echo 0)"
HIST_AFTER="$(cat "$ART/historian_count_after.txt")"

if [[ "$PQ_AFTER" -ge "$PQ_BEFORE" ]]; then
  ok "parquet_file_count preserved ($PQ_BEFORE → $PQ_AFTER)"
else
  bad "parquet_file_count dropped ($PQ_BEFORE → $PQ_AFTER) — volume may have been wiped"
fi

if [[ "$DATASETS_AFTER" -ge "$DATASETS_BEFORE" ]]; then
  ok "CSV/package datasets preserved ($DATASETS_BEFORE → $DATASETS_AFTER)"
else
  bad "dataset count dropped ($DATASETS_BEFORE → $DATASETS_AFTER)"
fi

if [[ "$HIST_AFTER" -ge "$HIST_BEFORE" ]]; then
  ok "historian file tree preserved ($HIST_BEFORE → $HIST_AFTER files)"
else
  bad "historian files dropped ($HIST_BEFORE → $HIST_AFTER)"
fi

# ingest_ok is a process counter — may reset on container recreate even when Parquet
# on the bind-mount volume is intact. Durability proof = parquet + historian + datasets.
if [[ "$INGEST_AFTER" -ge "$INGEST_BEFORE" ]]; then
  ok "ingest_ok monotonic ($INGEST_BEFORE → $INGEST_AFTER) — streamed MQTT history retained"
elif [[ "$PQ_AFTER" -ge "$PQ_BEFORE" && "$HIST_AFTER" -ge "$HIST_BEFORE" ]]; then
  skip "ingest_ok reset ($INGEST_BEFORE → $INGEST_AFTER) after recreate — counter is runtime; volume data preserved"
else
  bad "ingest_ok regressed ($INGEST_BEFORE → $INGEST_AFTER) with volume data loss"
fi

# Spot-check a known CSV building if present
if jq -e '.building_id' "$ART/parquet_manifest_before.json" >/dev/null 2>&1; then
  BID="$(jq -r '.building_id' "$ART/parquet_manifest_before.json")"
  if jq -e --arg b "$BID" '.building_id == $b' "$ART/parquet_manifest_after.json" >/dev/null 2>&1; then
    ok "parquet manifest building_id=$BID unchanged after recreate"
  else
    bad "parquet manifest building_id mismatch after recreate"
  fi
  GM_BEFORE="$(jq -r '.grid_minutes // empty' "$ART/parquet_manifest_before.json")"
  GM_AFTER="$(jq -r '.grid_minutes // empty' "$ART/parquet_manifest_after.json")"
  if [[ -n "$GM_BEFORE" && "$GM_BEFORE" == "$GM_AFTER" ]]; then
    ok "manifest grid_minutes=$GM_BEFORE preserved (CSV poll cadence)"
  fi
fi

cat >"$ART/restore_smoke_summary.txt" <<EOF
# Volume restore smoke $(date -u +%Y-%m-%dT%H:%M:%SZ)
parquet_files: $PQ_BEFORE → $PQ_AFTER
datasets: $DATASETS_BEFORE → $DATASETS_AFTER
historian_files: $HIST_BEFORE → $HIST_AFTER
ingest_ok: $INGEST_BEFORE → $INGEST_AFTER
Model: bind-mount workspace/ (local) or Railway /workspace volume — image tag change only.
Streamed MQTT → Parquet on volume; no per-message backup file required.
Disaster recovery: tar backup per backup-update-restore.md
EOF
ok "wrote $ART/restore_smoke_summary.txt"

summary
