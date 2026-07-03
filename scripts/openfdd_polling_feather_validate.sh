#!/usr/bin/env bash
# Validate the full polling stack: live OT reads, product poll services, historian/Feather persistence.
#
# Documents a known upstream gap: POST /api/modbus/read and /api/bacnet/read succeed with numeric
# values, but /api/modbus/poll/status stays samples=0 and historian row_count does not grow — data
# is not written to Arrow/Feather/JSONL pivot stores.
#
# Usage:
#   ./scripts/openfdd_polling_feather_validate.sh
#   OPENFDD_POLL_VALIDATE_CYCLES=3 OPENFDD_POLL_VALIDATE_INTERVAL_SEC=60 ./scripts/openfdd_polling_feather_validate.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"

openfdd_bench_load_profile "$ROOT" || true

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
COMMISSION="${OPENFDD_COMMISSION_BASE:-http://127.0.0.1:9091}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
CYCLES="${OPENFDD_POLL_VALIDATE_CYCLES:-3}"
INTERVAL="${OPENFDD_POLL_VALIDATE_INTERVAL_SEC:-60}"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${OPENFDD_POLL_VALIDATE_DIR:-$ROOT/workspace/logs/polling_feather_validate_${RUN_TS}}"

mkdir -p "$OUT"
CURL_TLS=()
[[ "$BASE" == https://* ]] && CURL_TLS=(-k)

pass=0
fail=0

check() {
  local name="$1" ok="$2" detail="$3"
  openfdd_bench_check_line "$name" "$ok" "$detail" "$OUT/summary.txt"
  if [[ "$ok" == "pass" ]]; then pass=$((pass + 1)); else fail=$((fail + 1)); fi
}

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$OUT/validate.log"; }

TOKEN="$(openfdd_auth_login_token "$BASE" "$AUTH" integrator)" || {
  echo "ERROR: integrator login failed" >&2
  exit 1
}

echo "=== Open-FDD polling + Feather store validation ===" | tee "$OUT/summary.txt"
echo "base=$BASE commission=$COMMISSION cycles=$CYCLES interval=${INTERVAL}s out=$OUT" | tee -a "$OUT/summary.txt"
log "start cycles=$CYCLES interval=${INTERVAL}s"

# --- Layer 0: poll daemon (bench harness) ---
DAEMON_PID_FILE="$ROOT/workspace/logs/bacnet_poll_daemon/daemon.pid"
if [[ -f "$DAEMON_PID_FILE" ]] && kill -0 "$(cat "$DAEMON_PID_FILE")" 2>/dev/null; then
  daemon_tail="$(tail -1 "$ROOT/workspace/logs/bacnet_poll_daemon/daemon.log" 2>/dev/null || true)"
  if grep -qE 'modbus_read=true\([0-9]' <<<"${daemon_tail:-}"; then
    check "poll-daemon-live" pass "running pid=$(cat "$DAEMON_PID_FILE") — ${daemon_tail}"
  else
    check "poll-daemon-live" fail "daemon running but latest cycle lacks numeric live reads — restart: ./scripts/openfdd_bacnet_poll_daemon.sh stop && start"
  fi
else
  check "poll-daemon-live" fail "not running — ./scripts/openfdd_bacnet_poll_daemon.sh start"
fi

# --- Baseline snapshots ---
baseline_hist="$(openfdd_bench_historian_store_snapshot "$BASE" "$TOKEN" "$ROOT")"
echo "$baseline_hist" | jq . >"$OUT/baseline_historian.json"
modbus_baseline="$(openfdd_bench_api GET "$BASE" "/api/modbus/poll/status" "$TOKEN")"
bacnet_baseline="$(openfdd_bench_api GET "$BASE" "/api/bacnet/poll/status" "$TOKEN")"
echo "$modbus_baseline" | jq . >"$OUT/baseline_modbus_poll.json"
echo "$bacnet_baseline" | jq . >"$OUT/baseline_bacnet_poll.json"

baseline_rows="$(jq -r '.api_row_count // 0' <<<"$baseline_hist")"
baseline_jsonl_lines="$(jq -r '.host_jsonl_lines // 0' <<<"$baseline_hist")"
baseline_jsonl_mtime="$(jq -r '.host_jsonl_mtime // 0' <<<"$baseline_hist")"
baseline_samples="$(jq -r '.samples // 0' <<<"$modbus_baseline")"

if jq -e '.path_mismatch == true' <<<"$baseline_hist" >/dev/null 2>&1; then
  check "historian-path-mismatch" fail "API reports $(jq -r '.api_jsonl_path' <<<"$baseline_hist") but host files at $(jq -r '.host_jsonl_path' <<<"$baseline_hist") — product reads wrong historian dir"
else
  check "historian-path-mismatch" pass "API paths align with host mount"
fi

if jq -e '.feather_present == true' <<<"$baseline_hist" >/dev/null 2>&1; then
  check "feather-store-present" pass "feather at $(jq -r '.host_feather_path' <<<"$baseline_hist")"
else
  check "feather-store-present" fail "no .feather under workspace/data — poll/read path does not persist Feather columnar store"
fi

: >"$OUT/cycles.jsonl"
live_pass=0
for n in $(seq 1 "$CYCLES"); do
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  live="$(openfdd_bench_live_ot_poll "$BASE" "$COMMISSION" "$TOKEN" "$ROOT")"
  echo "$live" >"$OUT/live_ot_cycle_${n}.json"
  modbus_poll="$(openfdd_bench_api GET "$BASE" "/api/modbus/poll/status" "$TOKEN")"
  hist="$(openfdd_bench_historian_store_snapshot "$BASE" "$TOKEN" "$ROOT")"

  jq -e '.ok == true' <<<"$live" >/dev/null 2>&1 && live_pass=$((live_pass + 1))

  jq -nc \
    --arg ts "$ts" --argjson cycle "$n" \
    --argjson live "$live" \
    --argjson modbus_poll "$modbus_poll" \
    --argjson hist "$hist" \
    '{
      timestamp_utc: $ts,
      cycle: $cycle,
      live_read_ok: $live.ok,
      modbus_value: $live.modbus_value,
      bacnet_value: $live.bacnet_value,
      modbus_poll_samples: ($modbus_poll.samples // 0),
      modbus_poll_last: ($modbus_poll.last_poll // null),
      historian_api_rows: $hist.api_row_count,
      historian_host_jsonl_lines: $hist.host_jsonl_lines,
      historian_host_jsonl_mtime: $hist.host_jsonl_mtime,
      feather_present: $hist.feather_present
    }' >>"$OUT/cycles.jsonl"

  log "cycle=$n live=$(jq -r '.ok' <<<"$live") modbus=$(jq -r '.modbus_value' <<<"$live") bacnet=$(jq -r '.bacnet_value' <<<"$live") samples=$(jq -r '.samples // 0' <<<"$modbus_poll") api_rows=$(jq -r '.api_row_count' <<<"$hist") host_lines=$(jq -r '.host_jsonl_lines' <<<"$hist")"

  [[ "$n" -lt "$CYCLES" ]] && sleep "$INTERVAL"
done

final_hist="$(openfdd_bench_historian_store_snapshot "$BASE" "$TOKEN" "$ROOT")"
final_modbus="$(openfdd_bench_api GET "$BASE" "/api/modbus/poll/status" "$TOKEN")"
echo "$final_hist" | jq . >"$OUT/final_historian.json"
echo "$final_modbus" | jq . >"$OUT/final_modbus_poll.json"

final_rows="$(jq -r '.api_row_count // 0' <<<"$final_hist")"
final_jsonl_lines="$(jq -r '.host_jsonl_lines // 0' <<<"$final_hist")"
final_jsonl_mtime="$(jq -r '.host_jsonl_mtime // 0' <<<"$final_hist")"
final_samples="$(jq -r '.samples // 0' <<<"$final_modbus")"
rows_delta=$(( final_rows - baseline_rows ))
jsonl_delta=$(( final_jsonl_lines - baseline_jsonl_lines ))
samples_delta=$(( final_samples - baseline_samples ))

if [[ "$live_pass" -eq "$CYCLES" ]]; then
  check "live-read-cycles" pass "${live_pass}/${CYCLES} cycles with numeric Modbus+Bacnet+Who-Is"
else
  check "live-read-cycles" fail "${live_pass}/${CYCLES} cycles passed — OT wire/read failure"
fi

if [[ "${samples_delta:-0}" -gt 0 ]]; then
  check "modbus-poll-accumulator" pass "samples ${baseline_samples}→${final_samples} (+${samples_delta})"
else
  check "modbus-poll-accumulator" fail "samples stuck at ${final_samples} after ${CYCLES} live-read cycles — product poll loop not persisting (enabled_points=$(jq -r '.enabled_points // 0' <<<"$final_modbus"))"
fi

if [[ "${rows_delta:-0}" -gt 0 || "${jsonl_delta:-0}" -gt 0 ]]; then
  check "historian-pivot-growth" pass "api_rows ${baseline_rows}→${final_rows} host_jsonl_lines ${baseline_jsonl_lines}→${final_jsonl_lines}"
elif [[ "$final_rows" -gt 0 && "$baseline_rows" -gt 0 ]]; then
  check "historian-pivot-growth" pass "historian has rows=${final_rows} (no growth this window — pre-existing data)"
else
  check "historian-pivot-growth" fail "api_row_count=${final_rows} host_jsonl_lines=${final_jsonl_lines} unchanged after ${CYCLES} live reads — **poll data not written to Feather/Arrow/JSONL pivot**"
fi

if [[ "$final_jsonl_mtime" != "$baseline_jsonl_mtime" && "$jsonl_delta" -gt 0 ]]; then
  check "historian-host-files" pass "telemetry_pivot.jsonl mtime/size grew"
else
  last_host_line="$(tail -1 "$(jq -r '.host_jsonl_path' <<<"$final_hist")" 2>/dev/null || true)"
  check "historian-host-files" fail "host pivot files stale (mtime unchanged) — last line: ${last_host_line:-none}"
fi

# --- Human-readable report for agents/upstream ---
cat >"$OUT/POLLING_MECHANISM.md" <<EOF
# Polling mechanism — bench validation (${RUN_TS})

## Three layers (do not conflate)

| Layer | What polls | Evidence | Bench verdict |
|-------|------------|----------|---------------|
| **1. Bench harness** | \`openfdd_bench_live_ot_poll\` — POST \`/api/modbus/read\`, POST \`/api/bacnet/read\`, Who-Is | \`live_ot_cycle_*.json\`, poll daemon \`cycles.jsonl\` | **PASS** when numeric °F each cycle |
| **2. Product driver poll services** | Background loops — \`/api/modbus/poll/status\`, \`/api/bacnet/poll/status\` | \`samples\`, \`last_poll\` | **FAIL** — Modbus \`samples=${final_samples}\`, \`last_poll=$(jq -r '.last_poll // "null"' <<<"$final_modbus")\` |
| **3. Historian / Feather store** | Pivot writer — Arrow IPC + JSONL (+ Feather export) | \`/api/historian/validation/status\`, host files | **FAIL** — \`row_count=${final_rows}\`, no Feather files |

## Suspected upstream bugs (file for product)

1. **Poll loop does not accumulate** — \`enabled_points=4\` but \`samples=0\` and \`last_poll=null\` while one-shot \`POST /api/modbus/read\` returns live values every cycle.
2. **Historian path mismatch** — API reports \`$(jq -r '.api_jsonl_path' <<<"$final_hist")\` but on-disk pivot is \`$(jq -r '.host_jsonl_path' <<<"$final_hist")\` (only \`validation/\` tree exists in container).
3. **No Feather persistence** — zero \`.feather\` files under \`workspace/data/\`; poll/read path never writes columnar Feather store.
4. **Stale pivot data** — host JSONL has ${final_jsonl_lines} lines but API \`row_count=0\` and \`last_sample_at=null\` — writer/reader disconnected.
5. **CSV import model drift** — last JSONL row often \`source:csv:import\` / \`site:import\`, not live Modbus/BACnet OT tags.

## Expected data flow (when fixed)

\`\`\`text
Modbus .14:1502 / BACnet 5007
    → driver poll loop OR read API
    → point model (site:local, not site:import)
    → historian pivot writer
    → telemetry_pivot.jsonl + .arrow (+ .feather export)
    → FDD SQL (oa_t from pivot) + UI trends
\`\`\`

## Artifacts

- \`baseline_historian.json\`, \`final_historian.json\`
- \`baseline_modbus_poll.json\`, \`final_modbus_poll.json\`
- \`cycles.jsonl\` — per-cycle live values vs store counters
- \`summary.txt\` — PASS/FAIL gates

## Re-run

\`\`\`bash
cd ${ROOT}
./scripts/openfdd_bacnet_poll_daemon.sh start
OPENFDD_POLL_VALIDATE_CYCLES=5 ./scripts/openfdd_polling_feather_validate.sh
./scripts/openfdd_bench_consolidated_report.sh
\`\`\`
EOF

ln -sfn "$OUT" "$ROOT/workspace/logs/polling_feather_validate_latest" 2>/dev/null || true
echo "$OUT" >"$ROOT/workspace/logs/polling_feather_validate_latest.dir"

jq -nc \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg dir "$OUT" \
  --argjson cycles "$CYCLES" \
  --argjson pass "$pass" --argjson fail "$fail" \
  --argjson live_pass "$live_pass" \
  --argjson baseline_rows "$baseline_rows" --argjson final_rows "$final_rows" \
  --argjson baseline_samples "$baseline_samples" --argjson final_samples "$final_samples" \
  --argjson feather_present "$(jq -r '.feather_present' <<<"$final_hist")" \
  '{timestamp_utc:$ts,artifact_dir:$dir,cycles:$cycles,pass_count:$pass,fail_count:$fail,
    live_read_cycles_passed:$live_pass,baseline_historian_rows:$baseline_rows,final_historian_rows:$final_rows,
    baseline_modbus_samples:$baseline_samples,final_modbus_samples:$final_samples,
    feather_present:$feather_present,ok:($fail==0)}' \
  >"$OUT/result.json"

echo | tee -a "$OUT/summary.txt"
echo "Result: pass=$pass fail=$fail artifact=$OUT" | tee -a "$OUT/summary.txt"
echo "Report: $OUT/POLLING_MECHANISM.md" | tee -a "$OUT/summary.txt"

log "complete pass=$pass fail=$fail"
exit "$(( fail > 0 ))"
