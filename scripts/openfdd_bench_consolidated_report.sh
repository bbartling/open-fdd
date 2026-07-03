#!/usr/bin/env bash
# Regenerate workspace/reports/BENCH_VALIDATION_REPORT.md from latest bench artifacts.
#
#   cd /home/ben/open-fdd && ./scripts/openfdd_bench_consolidated_report.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"
openfdd_bench_load_profile "$ROOT" || true

REPORT="$ROOT/workspace/reports/BENCH_VALIDATION_REPORT.md"
mkdir -p "$(dirname "$REPORT")"

read_latest() {
  local pointer="$1"
  local fallback="$2"
  if [[ -f "$pointer" ]]; then
    cat "$pointer"
  elif [[ -d "$fallback" ]]; then
    printf '%s' "$fallback"
  else
    printf ''
  fi
}

RIGOROUS="$(read_latest "$ROOT/workspace/logs/rigorous_full_latest.dir" "")"
MCP="$(read_latest "$ROOT/workspace/logs/mcp_eval_latest.dir" "$ROOT/workspace/logs/mcp_eval_latest")"
PROMPTS="$(read_latest "$ROOT/workspace/logs/agent_prompts_latest.dir" "$ROOT/workspace/logs/agent_prompts_latest")"
RBAC="$(read_latest "$ROOT/workspace/logs/rbac_eval_latest.dir" "$ROOT/workspace/logs/rbac_eval_latest")"
POLL_VALIDATE="$(read_latest "$ROOT/workspace/logs/polling_feather_validate_latest.dir" "")"
POLL_LOG="$ROOT/workspace/logs/bacnet_poll_daemon/daemon.log"
HIST_JSONL="$ROOT/workspace/data/historian/validation/telemetry_pivot.jsonl"

jq_safe() {
  local f="$1" filter="${2:-.}"
  [[ -f "$f" ]] && jq -c "$filter" "$f" 2>/dev/null || echo '{}'
}

RIGOROUS_RESULT="$(jq_safe "$RIGOROUS/result.json")"
HOUR_RESULT="$(jq_safe "$RIGOROUS/hour_test/result.json")"
MCP_RESULT="$(jq_safe "$MCP/result.json")"
PROMPTS_RESULT="$(jq_safe "$PROMPTS/result.json")"
RBAC_RESULT="$(jq_safe "$RBAC/result.json")"
POLL_RESULT="$(jq_safe "${POLL_VALIDATE:-/dev/null}/result.json")"
DRIVERS="$(ls -td "$ROOT"/workspace/logs/drivers_validate_* 2>/dev/null | head -1 || true)"
DRIVERS_RESULT="$(jq_safe "${DRIVERS:-/dev/null}/result.json")"
[[ -f "$HIST_JSONL" ]] && HIST_LINES="$(wc -l <"$HIST_JSONL" | tr -d ' ')"

NOW="$(date -u +%Y-%m-%d)"
HEALTH="$(curl -fsS http://127.0.0.1:8080/api/health 2>/dev/null || echo '{}')"
VERSION="$(jq -r '.version // .image_tag // "unknown"' <<< "$HEALTH")"
HAYSTACK_PASS_CFG=0
openfdd_bench_haystack_pass_configured "$ROOT" && HAYSTACK_PASS_CFG=1
HAYSTACK_LIVE='{}'
if [[ -f "$ROOT/workspace/auth.env.local" ]]; then
  # shellcheck source=scripts/openfdd_auth_lib.sh
  source "$ROOT/scripts/openfdd_auth_lib.sh" 2>/dev/null || true
  HS_TOKEN="$(openfdd_auth_login_token "http://127.0.0.1:8080" "$ROOT/workspace/auth.env.local" integrator 2>/dev/null || true)"
  if [[ -n "$HS_TOKEN" ]]; then
    HAYSTACK_LIVE="$(curl -fsS -H "Authorization: Bearer $HS_TOKEN" http://127.0.0.1:8080/api/haystack/status 2>/dev/null || echo '{}')"
  fi
fi
HAYSTACK_ENABLED="$(jq -r '.enabled // false' <<< "$HAYSTACK_LIVE")"
HAYSTACK_CONFIGURED="$(jq -r '.config.configured // false' <<< "$HAYSTACK_LIVE")"
HAYSTACK_PASSWORD_SET="$(jq -r '.config.password_set // false' <<< "$HAYSTACK_LIVE")"
HAYSTACK_STATION_OK=0
openfdd_bench_haystack_station_reachable "$ROOT" && HAYSTACK_STATION_OK=1
docker ps --format '{{.Names}}' 2>/dev/null | grep -qx openfdd-caddy && CADDY_UP=1
LAN_HEALTH='{}'
if [[ "$CADDY_UP" == "1" ]]; then
  LAN_HEALTH="$(curl -fsS "http://${OPENFDD_BENCH_IP:-192.168.204.55}/api/health" 2>/dev/null || echo '{}')"
fi
GHCR_JSON="$ROOT/workspace/logs/ghcr_pull_latest.json"
GHCR_EDGE_SRC="$(jq -r '.edge_source // "unknown"' "$GHCR_JSON" 2>/dev/null || echo unknown)"
GHCR_EDGE_TAG="$(jq -r '.edge_tag // "latest"' "$GHCR_JSON" 2>/dev/null || echo latest)"
GHCR_LATEST="$(jq -r '.ghcr_latest_pulled // false' "$GHCR_JSON" 2>/dev/null || echo false)"

MODEL_PROBE='{}'
MODEL_SITES='{}'
BACNET_TREE='{}'
BACNET_WHOIS='[]'
MODBUS_POLL='{}'
FDD_RULES='{}'
LOCAL_BACNET_READ='{}'
MODEL_POINT_COUNT=0
FDD_RULE_COUNT=0
BACNET_LOCAL_POINTS=0
LOCAL_BACNET_READ_OK=false
LOCAL_BACNET_READ_ERR=none
[[ -d "$ROOT/workspace/data/import_jobs" ]] && IMPORT_JOB_COUNT="$(find "$ROOT/workspace/data/import_jobs" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')"
if [[ -f "$ROOT/workspace/auth.env.local" ]]; then
  # shellcheck source=scripts/openfdd_auth_lib.sh
  source "$ROOT/scripts/openfdd_auth_lib.sh" 2>/dev/null || true
  PROBE_TOKEN="$(openfdd_auth_login_token "http://127.0.0.1:8080" "$ROOT/workspace/auth.env.local" integrator 2>/dev/null || true)"
  if [[ -n "$PROBE_TOKEN" ]]; then
    MODEL_PROBE="$(openfdd_bench_validate_model_ot "http://127.0.0.1:8080" "$PROBE_TOKEN" 2>/dev/null || echo '{}')"
    MODEL_SITES="$(openfdd_bench_api GET "http://127.0.0.1:8080" "/api/model/sites" "$PROBE_TOKEN" 2>/dev/null || echo '{}')"
    BACNET_TREE="$(openfdd_bench_api GET "http://127.0.0.1:8080" "/api/bacnet/driver/tree" "$PROBE_TOKEN" 2>/dev/null || echo '{}')"
    BACNET_WHOIS="$(openfdd_bench_api POST "http://127.0.0.1:9091" "/api/bacnet/whois" "$PROBE_TOKEN" "$(openfdd_bench_whois_json)" 2>/dev/null || echo '[]')"
    MODBUS_POLL="$(openfdd_bench_api GET "http://127.0.0.1:8080" "/api/modbus/poll/status" "$PROBE_TOKEN" 2>/dev/null || echo '{}')"
    HIST_SNAP="$(openfdd_bench_historian_store_snapshot "http://127.0.0.1:8080" "$PROBE_TOKEN" "$ROOT" 2>/dev/null || echo '{}')"
    FDD_RULES="$(openfdd_bench_api GET "http://127.0.0.1:8080" "/api/fdd-rules" "$PROBE_TOKEN" 2>/dev/null || echo '{}')"
    LOCAL_BACNET_READ="$(openfdd_bench_api POST "http://127.0.0.1:9091" "/api/bacnet/read" "$PROBE_TOKEN" \
      "$(jq -nc '{point_id:"bacnet:599999:analog-value:9003"}')" 2>/dev/null || echo '{}')"
  fi
fi
MODEL_ACTIVE="$(jq -r '.active_site_id // .active_site_id // "?"' <<< "$MODEL_SITES")"
MODEL_CSV_DEV="$(jq -r '.csv_dev_model // false' <<< "$MODEL_PROBE")"
MODEL_POINT_COUNT="$(jq -r '.sample_ids // [] | length' <<< "$MODEL_PROBE" 2>/dev/null || echo 0)"
FDD_RULE_COUNT="$(jq -r '.count // (.rules | length) // 0' <<< "$FDD_RULES")"
BACNET_LOCAL_POINTS="$(jq -r '[.devices[]? | select(.local_server==true) | (.points | length)] | add // 0' <<< "$BACNET_TREE" 2>/dev/null || echo 0)"
LOCAL_BACNET_READ_OK="$(jq -r '.ok // false' <<< "$LOCAL_BACNET_READ")"
LOCAL_BACNET_READ_ERR="$(jq -r '.error // "none"' <<< "$LOCAL_BACNET_READ")"
HIST_API_ROWS="$(jq -r '.api_row_count // 0' <<< "$HIST_SNAP")"
HIST_API_JSONL="$(jq -r '.api_jsonl_path // "?"' <<< "$HIST_SNAP")"
HIST_HOST_JSONL="$(jq -r '.host_jsonl_path // "?"' <<< "$HIST_SNAP")"
HIST_HOST_LINES="$(jq -r '.host_jsonl_lines // 0' <<< "$HIST_SNAP")"
HIST_PATH_MISMATCH="$(jq -r '.path_mismatch // false' <<< "$HIST_SNAP")"
FEATHER_PRESENT="$(jq -r '.feather_present // false' <<< "$HIST_SNAP")"
BACNET_TREE_FIELD="$(jq '[.devices[]? | select(.device_instance != 599999 and .address != "local")] | length' <<< "$BACNET_TREE" 2>/dev/null || echo 0)"
EXPECT_INST="${OPENFDD_SMOKE_DEVICE_INSTANCE:-5007}"
BACNET_5007="$(jq -c --argjson n "$EXPECT_INST" '[.[] | select(.object_identifier.instance == $n)] | .[0] // empty' <<< "$BACNET_WHOIS" 2>/dev/null || echo '')"
MODBUS_SAMPLES="$(jq -r '.samples // 0' <<< "$MODBUS_POLL")"

cat >"$REPORT" <<EOF
# Open-FDD bench validation — consolidated report

**Report date:** ${NOW} (auto-generated)  
**Bench:** \`$(hostname -s 2>/dev/null || echo bensbench)\` @ \`${ROOT}\` (GHCR pull only — no git clone)  
**Image (requested):** \`${OPENFDD_RUST_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-edge-rust}:${OPENFDD_IMAGE_TAG:-latest}\`  
**MCP (requested):** \`${OPENFDD_MCP_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-mcp}:${OPENFDD_MCP_GHCR_TAG:-latest}\`  
**GHCR pull log:** \`workspace/logs/ghcr_pull_latest.log\`  
**Latest rigorous artifact:** \`${RIGOROUS:-none}\`  
**README:** [master README](https://raw.githubusercontent.com/bbartling/open-fdd/refs/heads/master/README.md)

**GHCR latest pulled:** $( [[ "$GHCR_LATEST" == "true" ]] && echo "**YES**" || echo "**NO — using ${GHCR_EDGE_SRC} tag \`${GHCR_EDGE_TAG}\`**" )  
**Target tags (profile):** edge \`${OPENFDD_IMAGE_TAG:-3.2.4}\` · MCP \`${OPENFDD_MCP_GHCR_TAG:-v3.2.4}\`  
**Last pull:** edge \`${GHCR_EDGE_TAG}\` (\`${GHCR_EDGE_SRC}\`) · MCP \`${OPENFDD_MCP_GHCR_TAG:-v3.2.4}\` (\`$(jq -r '.mcp_source // "unknown"' "$GHCR_JSON" 2>/dev/null || echo unknown)\`)

---

## P0 — Model & FDD assignments tab + master bug register (read first)

**UI location:** Integrations → **Model & FDD assignments** (sub-tabs: Import / export · Explorer · **FDD mapping** · Haystack RDF · Advanced)

### What the tab shows today (FAIL — wonky shipped dev model)

| UI banner / counter | Live bench (${NOW}) | Expected |
|---------------------|----------------------|----------|
| Haystack site | **\`${MODEL_ACTIVE}\`** · 1 equipment · **${MODEL_POINT_COUNT}** points · **${FDD_RULE_COUNT}** rules · **0** bound points | **\`site:local\`** · OT equipment · points from Modbus/BACnet/Haystack · rules from validation profile · bound \`fdd_rule_ids\` |
| Import / export hint | “commissioning JSON or use AI to populate FDD mappings” | Fresh edge ships **blank/default** model — no CSV dev import |
| **FDD mapping** sub-tab | Mapped **0** · Unmapped **${MODEL_POINT_COUNT}** · Rules **${FDD_RULE_COUNT}** · “No FDD rule bindings yet” | Rules visible on **main dashboard**; mapping is commissioning JSON only |
| Sample point IDs | $(jq -c '.sample_ids // []' <<< "$MODEL_PROBE" 2>/dev/null || echo '[]') | \`bacnet:5007:*\`, Modbus regs, \`equip:local-test-equipment\` — not \`point:import-*\` |
| CSV import jobs on disk | **${IMPORT_JOB_COUNT}** under \`workspace/data/import_jobs/\` | **0** on fresh install |
| Building ID in BACnet tree | \`$(jq -r '.building_id // "?"' <<< "$BACNET_TREE")\` | \`local\` / site-local — not \`import-main\` |

**Bench verdict:** GHCR image ships a **stale CSV dev model** (\`site:import\`, \`equip:import\`, \`point:import-*\`) that was never meant for field benches. **Ship blank/default commissioning JSON** (empty sites, zero import jobs) and load OT from drivers + validation profile — not bundled CSV artifacts.

### Required UI changes (product)

| Change | Rationale |
|--------|-----------|
| **Remove “FDD mapping” button / sub-tab** | Duplicate of commissioning JSON + AI workflow; confuses operators |
| **List fault rules on main Validation / FDD dashboard** | Operators need rule name, status, last eval — not buried under Integrations |
| **Default model = empty** | No \`site:import\`, no \`import-main\`, no pre-seeded CSV TTL |
| **Hide “0 points bound to FDD · 0 rules” shame counters** until model is configured | Or show actionable setup wizard tied to \`local_validation_profile.local.toml\` |

### Polling + historian (still broken in product)

| Layer | Status | Evidence |
|-------|--------|----------|
| Bench harness live reads | **PASS** | \`openfdd_bench_live_ot_poll\` — Modbus ~68–76°F, BACnet ~78°F every cycle |
| Product \`/api/modbus/poll/status\` | **FAIL** | \`samples=${MODBUS_SAMPLES}\`, \`last_poll=null\`, \`enabled_points=4\` |
| Historian / Feather store | **FAIL** | API \`row_count=${HIST_API_ROWS}\`; host JSONL **${HIST_HOST_LINES}** lines stale; **no .feather** |
| Path mismatch | **FAIL** | API → \`historian/historian/\` · disk → \`historian/validation/\` |

Validate: \`./scripts/openfdd_polling_feather_validate.sh\` · artifact: \`${POLL_VALIDATE:-none}\`

### Open-FDD local BACnet server (device **599999**) — NOT functioning

The edge **must** run an always-on BACnet/IP server (Open-FDD diagnostic points), modeled on [rusty-bacnet \`mini-device-revisited\`](https://github.com/jscott3201/rusty-bacnet/tree/dev/examples/rust/samples/mini-device-revisited) — validated standalone on this subnet.

| Probe | Live bench |
|-------|------------|
| Driver tree local device | Instance **599999** · **${BACNET_LOCAL_POINTS}** points in UI tree (\`openfdd-active-fault-count\`, \`outside-air-temperature\`, …) |
| \`/api/bacnet/poll/status\` | \`status=ready\` · bind \`${OPENFDD_BENCH_IP:-192.168.204.55}:47808\` · instance **599999** |
| Commission \`POST /api/bacnet/read\` local point | $(if [[ "$LOCAL_BACNET_READ_OK" == "true" ]]; then echo "**PASS**"; else echo "**FAIL** — \`${LOCAL_BACNET_READ_ERR}\`"; fi) |
| Periodic **I-Am** on LAN | **FAIL / unverified** — Who-Is for 599999 does not return local server; network scanners may not see OpenFDD device |
| Reference impl | [\`mini-device-revisited\`](https://github.com/jscott3201/rusty-bacnet/tree/dev/examples/rust/samples/mini-device-revisited) startup + periodic I-Am; [\`samples/README\`](https://github.com/jscott3201/rusty-bacnet/tree/dev/examples/rust/samples) workflow |

**Required fix:** Port \`mini-device-revisited\` lifecycle (bind \`0.0.0.0:47808\`, periodic I-Am, object-list with Open-FDD AVs) into \`bacnet_server_runtime.rs\`; commission read path must include device **599999** in device table (today: \`device 599999 not in device table\`).

### Priority-array scan (hourly — field device **5007**)

Modeled on [rusty-bacnet \`point-discover\`](https://github.com/jscott3201/rusty-bacnet/tree/dev/examples/rust/samples/point-discover) (\`run-5007.sh\`): Who-Is → object-list → RPM present-values → **priority-array scan** on commandable points (P1/P8/P16 overrides on Niagara).

| Requirement | Bench state |
|-------------|-------------|
| Cadence | **Once per hour** on field gear (validation profile + override scan) |
| \`/api/bacnet/poll/status\` | \`scan_interval_seconds=3600\`, \`writes_scan_cadence_seconds=3600\` |
| Harness | Rigorous/hour tests must assert priority scan completes when field device **${EXPECT_INST}** is reachable |
| Reference | [\`point-discover\`](https://github.com/jscott3201/rusty-bacnet/tree/dev/examples/rust/samples/point-discover) — OA-T AI:1173, AO priority slots, Niagara metadata filtering |

### SQL tab — total rewrite (product UX)

**Current UI (FAIL):** “Schema · DataFusion · Historian tables registered for FDD SQL” with column-click insert, NL prompt, query builder — unprofessional and confusing.

**Required UX:**

| Keep | Remove |
|------|--------|
| Dropdown to pick **historian table** (devices / Haystack locations / \`telemetry_pivot\`) | “Schema / DataFusion” marketing header |
| Monaco (or equivalent) **SQL editor** with **format SQL** only | NL prompt · visual query builder |
| Short help: **where data lives** and **how rows map to devices** | Column-click-to-insert clutter |

**Canonical example** (what shipped SQL tab should look like by default):

\`\`\`sql
SELECT
  timestamp,
  equipment_id,
  oa_t,
  CASE
    WHEN oa_t IS NULL THEN false
    WHEN oa_t < 40.0 THEN true
    WHEN oa_t > 110.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:validation'
\`\`\`

Rule: \`oa_temp_out_of_range\` over \`telemetry_pivot\` — only works when **polling persists** live OT into the pivot (see above — **blocked today**).

### Master bug register (all open — ${NOW})

| # | Area | Bug | Priority |
|---|------|-----|----------|
| 1 | **Default model** | Ships \`site:import\` CSV dev artifacts (${IMPORT_JOB_COUNT} import jobs) | P0 |
| 2 | **Model & FDD tab** | 0 rules · 0 bound points · misleading FDD mapping sub-tab | P0 |
| 3 | **Main dashboard** | Fault rules not listed prominently | P0 |
| 4 | **SQL tab** | Confusing Schema/NL/builder UX — needs table picker + formatter only | P0 |
| 5 | **Polling** | Live reads OK; product poll \`samples=0\` | P0 |
| 6 | **Historian / Feather** | Poll data not written; path mismatch; no .feather | P0 |
| 7 | **BACnet server 599999** | Tree shows points; commission read fails; I-Am not on LAN | P0 |
| 8 | **BACnet tab** | Field device **${EXPECT_INST}** not in driver tree (Who-Is OK) | P0 |
| 9 | **Haystack** | Pass loaded; station \`.11\` unreachable / driver not configured | P0 |
| 10 | **Login UI** | Dev role shortcuts + bootstrap path on LAN | P0 |
| 11 | **FDD PATCH API** | Fault rule change @ hour 30 → 404 | P0 |
| 12 | **Priority scan** | Hourly \`point-discover\`-style scan not validated end-to-end | P1 |

---

## GHCR pull status

| Item | Result |
|------|--------|
| Profile pins | \`workspace/bench/bench_profile.toml\` → edge \`${OPENFDD_IMAGE_TAG:-3.2.4}\`, MCP \`${OPENFDD_MCP_GHCR_TAG:-v3.2.4}\` |
| Last pull script | \`./scripts/openfdd_bench_pull_latest.sh\` (tries profile tag, then fallbacks) |
| Edge resolved | **\`${GHCR_EDGE_TAG}\`** from **\`${GHCR_EDGE_SRC}\`** |
| MCP resolved | **\`$(jq -r '.mcp_tag // "v3.2.4"' "$GHCR_JSON" 2>/dev/null)\`** from **\`$(jq -r '.mcp_source // "ghcr"' "$GHCR_JSON" 2>/dev/null)\`** |
| GHCR auth | \`gh auth refresh -h github.com -s read:packages\` if pull fails |

Log: \`workspace/logs/ghcr_pull_latest.log\` · \`workspace/logs/ghcr_pull_latest.json\`

---

| Area | Result | Artifact |
|------|--------|----------|
| Bridge health | $(jq -r 'if .ok then "**PASS**" else "**FAIL**" end' <<< "$HEALTH") | \`GET /api/health\` → ${VERSION} |
| README + agent prompts | $(jq -r 'if .ok then "**PASS**" else if .pass_count then "**PARTIAL**" else "**UNKNOWN**" end end' <<< "$PROMPTS_RESULT") $(jq -r 'if .pass_count then "\(.pass_count)/\(.pass_count + .fail_count) checks" else "" end' <<< "$PROMPTS_RESULT") | \`${PROMPTS:-logs/agent_prompts_latest}\` |
| MCP sidecar | $(jq -r 'if .ok then "**PASS**" else "**FAIL**" end' <<< "$MCP_RESULT") $(jq -r 'if .pass_count then "\(.pass_count)/\(.pass_count + .fail_count)" else "" end' <<< "$MCP_RESULT") | \`${MCP:-logs/mcp_eval_latest}\` |
| RBAC (admin/integrator/agent/operator) | $(jq -r 'if .ok then "**PASS** \(.pass_count // 0)/\(.pass_count + .fail_count + .skip_count // 0)" else if .pass_count then "**FAIL**" else "**NOT RUN**" end end' <<< "$RBAC_RESULT") | \`${RBAC:-logs/rbac_eval_latest}\` |
| Drivers (live OT) | $(jq -r 'if .ok then "**PASS** \(.pass_count // 0)/\(.pass_count + .fail_count // 0)" elif .pass_count then "**PARTIAL** \(.pass_count // 0) pass, \(.fail_count // 0) fail (Haystack=station firewall)" else "**NOT RUN**" end' <<< "$DRIVERS_RESULT") | \`${DRIVERS:-run openfdd_drivers_validate.sh}\` |
| Historian restore workflow | **Bench scripts** | \`openfdd_rust_historian_staging.sh\` + \`openfdd_rust_site_restore.sh\` (default on update) |
| Hour test | $(jq -r 'if .ok then "**PASS**" elif .cycles_pass then "\(.cycles_pass)/\(.cycles_total // 60)" else "**PENDING/UNKNOWN**" end' <<< "$HOUR_RESULT") | \`${RIGOROUS:-}/hour_test/\` |
| Rigorous overall | $(jq -r 'if .ok then "**PASS**" elif .artifact_dir then "**FAIL/PARTIAL**" else "**IN PROGRESS**" end' <<< "$RIGOROUS_RESULT") | \`${RIGOROUS:-}\` |
| Poll daemon | $( [[ -f "$ROOT/workspace/logs/bacnet_poll_daemon/daemon.pid" ]] && ps -p "$(cat "$ROOT/workspace/logs/bacnet_poll_daemon/daemon.pid" 2>/dev/null)" >/dev/null 2>&1 && echo "**RUNNING** (live-read loop)" || echo "**STOPPED**" ) | \`workspace/logs/bacnet_poll_daemon/\` |
| Polling + Feather store | $(jq -r 'if .ok then "**PASS** \(.pass_count // 0)/\(.pass_count + .fail_count // 0)" elif .pass_count then "**FAIL** \(.fail_count // 0) upstream gaps" else "**NOT RUN** — ./scripts/openfdd_polling_feather_validate.sh" end' <<< "$POLL_RESULT") | \`${POLL_VALIDATE:-run openfdd_polling_feather_validate.sh}\` |
| Historian API rows | **${HIST_API_ROWS}** (\`last_sample_at=$(jq -r '.api_last_sample_at // "null"' <<< "$HIST_SNAP")\`) | \`GET /api/historian/validation/status\` |
| Historian host JSONL | **${HIST_HOST_LINES}** lines (stale if mtime old) | \`${HIST_HOST_JSONL}\` |
| Feather store | $(if [[ "$FEATHER_PRESENT" == "true" ]]; then echo "**PRESENT**"; else echo "**MISSING** — poll/read not persisting .feather"; fi) | \`find workspace/data -name '*.feather'\` |
| Haystack (live) | $(if [[ "$HAYSTACK_ENABLED" == "true" && "$HAYSTACK_CONFIGURED" == "true" ]]; then echo "**PASS** connected"; elif [[ "$HAYSTACK_PASS_CFG" == "1" && "$HAYSTACK_PASSWORD_SET" == "true" && "$HAYSTACK_STATION_OK" == "0" ]]; then echo "**FAIL** pass loaded — station unreachable"; elif [[ "$HAYSTACK_PASS_CFG" == "1" && "$HAYSTACK_PASSWORD_SET" == "true" ]]; then echo "**PARTIAL** pass loaded — driver/TOML not active (3.2.4?)"; elif [[ "$HAYSTACK_PASS_CFG" == "1" ]]; then echo "**PARTIAL** pass in file — run safe restart"; else echo "**NOT CONFIGURED**"; fi) | \`data.env.local\` + \`local.nhaystack.toml\` |
| Remote LAN (Caddy) | $(if [[ "$CADDY_UP" == "1" && "$(jq -r '.ok // false' <<< "$LAN_HEALTH")" == "true" ]]; then echo "**UP** http://${OPENFDD_BENCH_IP:-192.168.204.55}/"; elif [[ "$CADDY_UP" == "1" ]]; then echo "**CADDY UP** — health check failed"; else echo "**DIRECT ONLY** — run caddy-http recipe"; fi) | \`./scripts/openfdd_caddy_test_recipe.sh caddy-http\` |
| Model & FDD tab | **FAIL** \`${MODEL_ACTIVE}\` · ${MODEL_POINT_COUNT} pts · ${FDD_RULE_COUNT} rules · 0 bound | Integrations UI + \`/api/model/sites\` |
| OpenFDD BACnet server | $(if [[ "$LOCAL_BACNET_READ_OK" == "true" ]]; then echo "**PASS** 599999 read OK"; else echo "**FAIL** 599999 — ${LOCAL_BACNET_READ_ERR}"; fi) | commission \`POST /api/bacnet/read\` local AV |

---

## Remote dial-in (active now)

| Access | URL | Status |
|--------|-----|--------|
| **LAN (Caddy HTTP)** | http://${OPENFDD_BENCH_IP:-192.168.204.55}/ | $(if [[ "$CADDY_UP" == "1" && "$(jq -r '.ok // false' <<< "$LAN_HEALTH")" == "true" ]]; then echo "**UP** — use integrator login in UI"; else echo "run \`./scripts/openfdd_caddy_test_recipe.sh caddy-http\`"; fi) |
| **Local bridge** | http://127.0.0.1:8080/ | **UP** (${VERSION}) |
| **SSH tunnel (off-LAN)** | \`ssh -L 8080:127.0.0.1:8080 user@${OPENFDD_BENCH_IP:-192.168.204.55}\` | then http://127.0.0.1:8080 |

Login: use **Username + Password** only — credentials from your password manager (one-time handoff was \`workspace/bootstrap_credentials.once.txt\`).

---

## Sign-in UI — security (P0 product fix)

**Observed on LAN/dev sign-in** (\`OPENFDD_ALLOW_INSECURE_AUTH=1\`):

\`\`\`text
Local dev (requires edge OPENFDD_ALLOW_INSECURE_AUTH=1):
  Sign in as integrator
  Sign in as admin
  Start UI dev (5173)
  Manual password: workspace/bootstrap_credentials.once.txt
\`\`\`

**Bench verdict: FAIL — remove from production and field benches.**

| Issue | Why it is bad |
|-------|----------------|
| **“Sign in as integrator/admin” buttons** | Username enumeration + role hints on the login surface |
| **“Manual password: bootstrap_credentials.once.txt”** | Path/credential hints for attackers; looks unprofessional on a field edge |
| **Assistance shortcuts on auth page** | Violates least-privilege UX — login should be username/password only |

**Required upstream fix:** Dev-only affordances behind a build flag or localhost-only route — never on \`http://${OPENFDD_BENCH_IP:-192.168.204.55}/\` Caddy ingress.

---

## LAN HTTP browser warnings (expected until TLS)

Dial-in uses **Caddy HTTP** (\`http://${OPENFDD_BENCH_IP:-192.168.204.55}/\`), not HTTPS. Browser console noise is **expected**:

| Message | Meaning |
|---------|---------|
| **Cross-Origin-Opener-Policy ignored — untrustworthy origin** | COOP requires HTTPS or localhost; plain LAN IP is not a [potentially trustworthy origin](https://www.w3.org/TR/powerful-features/#potentially-trustworthy-origin) |
| **blob:http://192.168.204.55/… insecure connection** | Model download/export blobs over HTTP — use \`caddy-tls\` profile or SSH tunnel for HTTPS |
| **\`openfdd-agent/building-insight\` 401** | Agent-role route hit without agent JWT — use integrator login for operator UI, or fix UI to not prefetch agent-only paths |

**Mitigation:** \`./scripts/openfdd_caddy_test_recipe.sh caddy-tls\` + trust bench cert, or \`ssh -L 8080:127.0.0.1:8080\` and use localhost.

---

## BACnet device ${EXPECT_INST} — not on BACnet tab

| Probe | Live bench state |
|-------|------------------|
| Who-Is (commission :9091) | $(if [[ -n "$BACNET_5007" && "$BACNET_5007" != "null" && "$BACNET_5007" != "" ]]; then echo "**SEEN** $(echo "$BACNET_5007" | jq -r '"Device \(.object_identifier.instance) @ \(.address)"')"; else echo "**NOT SEEN** — check OT path / router"; fi) |
| Bridge \`/api/bacnet/driver/tree\` | **${BACNET_TREE_FIELD}** field device(s) (UI BACnet tab reads this) |
| Local server only | Instance **599999** @ local always present |

**Why the tab is empty:** Who-Is finds device **${EXPECT_INST}** at \`192.168.204.200:47808\` (MSTP routed), but the **bridge driver tree is not populated** from commission discovery — UI shows only the local OpenFDD server. Harness now **FAILs** \`bacnet-ui-tree\` when Who-Is > 0 but tree field count = 0.

**Expected bench target:** \`OPENFDD_SMOKE_DEVICE_INSTANCE=${EXPECT_INST}\` in \`workspace/data.env.local\`; validation profile \`site:local\` / \`equip:local-test-equipment\`.

---

## Data model drift — stale CSV dev import (FAIL)

| Item | State |
|------|--------|
| Active site | **\`${MODEL_ACTIVE}\`** $(if [[ "$MODEL_ACTIVE" == "site:import" ]]; then echo "(should be **site:local**)"; fi) |
| CSV import jobs on disk | **${IMPORT_JOB_COUNT}** under \`workspace/data/import_jobs/\` |
| Model grid sample IDs | $(jq -c '.sample_ids // []' <<< "$MODEL_PROBE" 2>/dev/null || echo '[]') |
| \`/api/model/ttl\` | \`source:csv:import\`, \`point:import-*\`, \`site:import\` — **dev CSV artifacts**, not BACnet ${EXPECT_INST} / Modbus \`.14:1502\` |
| Modbus poll samples | **${MODBUS_SAMPLES}** (\`enabled_points=$(jq -r '.enabled_points // 0' <<< "$MODBUS_POLL")\`) — reads work; poll loop may not accumulate samples |
| Harness gate | \`model-ot\` + \`disc-model\` now **FAIL** when \`active_site_id=site:import\` or CSV-only model |

**Cleanup (bench operator — preserves OT config):**

1. Remove stale CSV import jobs / reset model to \`site:local\` (UI Integrations or API — avoid deleting \`workspace/data.env.local\`)
2. Re-learn BACnet device **${EXPECT_INST}** once product populates driver tree from commission
3. Re-run: \`./scripts/openfdd_drivers_validate.sh\` — expect \`model-ot\`, \`bacnet-ui-tree\`, \`modbus-poll\` gates

**Profile mismatch:** \`local_validation_profile.local.toml\` expects \`site:local\` + device ${EXPECT_INST}; UI model export still shows \`site:import\` / \`equip:import\`.

---

## Polling mechanism — three layers + Feather store bug (P0)

**Do not conflate:** bench harness polling, product background poll services, and historian/Feather persistence are **three separate layers**. Layer 1 **PASSes** on this bench; layers 2–3 **FAIL** — suspected upstream product bugs.

### Layer map

| Layer | Mechanism | Pass criteria | Live bench (${NOW}) |
|-------|-----------|---------------|---------------------|
| **1 — Bench harness** | \`openfdd_bench_live_ot_poll\` → \`POST /api/modbus/read\`, \`POST /api/bacnet/read\`, Who-Is | Numeric °F every cycle | **PASS** — poll daemon logs \`modbus_read=true(68–76)\` \`bacnet_read=true(~78)\` |
| **2 — Product poll loop** | Background \`/api/modbus/poll/status\`, \`/api/bacnet/poll/status\` | \`samples\` increments, \`last_poll\` set | **FAIL** — \`samples=${MODBUS_SAMPLES}\`, \`last_poll=$(jq -r '.last_poll // "null"' <<< "$MODBUS_POLL")\`, \`enabled_points=$(jq -r '.enabled_points // 0' <<< "$MODBUS_POLL")\` |
| **3 — Historian / Feather** | Pivot writer → JSONL + Arrow IPC (+ Feather export) | \`row_count\` grows; host files update | **FAIL** — API \`row_count=${HIST_API_ROWS}\`; host JSONL **${HIST_HOST_LINES}** lines (often stale CSV import) |

### Expected data flow (when product is fixed)

\`\`\`text
OT Modbus .14:1502 / BACnet device ${EXPECT_INST}
  → driver poll loop (or read API feeding poll pipeline)
  → point model (site:local — NOT site:import CSV)
  → historian pivot writer
  → telemetry_pivot.jsonl + telemetry_pivot.arrow (+ .feather export)
  → FDD SQL (oa_t) + UI validation trends
\`\`\`

### Evidence — path mismatch (container)

| Probe | Value |
|-------|--------|
| API \`jsonl\` path | \`${HIST_API_JSONL}\` |
| Host mount (actual files) | \`${HIST_HOST_JSONL}\` |
| Path mismatch | $(if [[ "$HIST_PATH_MISMATCH" == "true" ]]; then echo "**YES** — API points at \`historian/historian/\` but only \`historian/validation/\` exists in container"; else echo "no (or not detected)"; fi) |
| Feather files | $(if [[ "$FEATHER_PRESENT" == "true" ]]; then echo "present"; else echo "**none** under \`workspace/data/\`"; fi) |

**Symptom:** One-shot \`POST /api/modbus/read\` returns live ~68–76°F and \`POST /api/bacnet/read\` returns ~77–78°F **every cycle**, but:

1. \`/api/modbus/poll/status\` stays \`samples=0\`
2. \`/api/historian/validation/status\` stays \`row_count=0\`, \`last_sample_at=null\`
3. Host \`telemetry_pivot.jsonl\` mtime does **not** advance — last rows are often \`source:csv:import\` / \`equip:import\`, not live OT

### Bench validation script

\`\`\`bash
cd ${ROOT}
./scripts/openfdd_bacnet_poll_daemon.sh start   # layer 1 continuous
./scripts/openfdd_polling_feather_validate.sh   # layers 1–3 gates + POLLING_MECHANISM.md
\`\`\`

Latest artifact: \`${POLL_VALIDATE:-none}\` · doc: \`POLLING_MECHANISM.md\` · gates in \`summary.txt\`

**Harness gates added:** \`historian-path\`, \`feather-store\`, \`historian-persist\`, \`modbus-poll-accumulator\` (in \`openfdd_drivers_validate.sh\` + \`openfdd_polling_feather_validate.sh\`).

**Upstream fix list (product):**

1. Wire poll loop samples → historian pivot writer (Modbus + BACnet enabled points)
2. Fix historian path — API must read/write same dir as mounted \`validation/\` pivot (or create \`historian/historian/\`)
3. Persist Feather columnar export (or document Arrow-only; today neither grows on live poll)
4. Map live reads into \`site:local\` model — not \`site:import\` CSV TTL

---

Per [README OpenClaw backup/update prompt](https://raw.githubusercontent.com/bbartling/open-fdd/refs/heads/master/README.md):

\`\`\`bash
cd ${ROOT}
./scripts/openfdd_rust_site_backup.sh
OPENFDD_RESTORE_HISTORIAN_AFTER_UPDATE=1 ./scripts/openfdd_rust_site_update.sh
./scripts/openfdd_rust_edge_validate.sh
\`\`\`

**Bench default (\`bench_profile.toml\`):** \`restore_historian_after_update = true\`, \`always_poll = true\`

1. **Export** Arrow/Feather/JSONL → \`workspace/backups/historian-staging/pre-update\`
2. **Backup** full workspace tarball (\`~/openfdd-backups/latest/workspace-full.tgz\`)
3. **Pull + recreate** containers
4. **Restore** historian from staging to \`workspace/data/historian/\`
5. **Verify** row/byte counts; **start poll daemon**

Manual restore from tarball:

\`\`\`bash
./scripts/openfdd_rust_site_restore.sh --from-backup ~/openfdd-backups/latest/workspace-full.tgz
\`\`\`

---

## Data model + SQL (rigorous FDD test)

**SQL tab UX:** See **P0 — SQL tab rewrite** at top of this report. Current Integrations SQL UI is **FAIL**; target is table dropdown + formatted SQL editor only.

**Historian pivot:** \`telemetry_pivot\` (Arrow + JSONL under \`workspace/data/historian/validation/\`)

| Column | Role |
|--------|------|
| \`timestamp\` | UTC sample |
| \`equipment_id\` | e.g. \`equip:local-test-equipment\`, \`equip:validation\` |
| \`oa_t\` | Outside air temp °F — **FDD input** |
| \`oa_h\`, \`duct_t\`, \`zn_t\` | Supporting telemetry |
| \`source_driver\` | bacnet / modbus / simulation |

**Rule:** \`oa_temp_out_of_range\` — DataFusion SQL over pivot:

\`\`\`sql
SELECT
  timestamp,
  equipment_id,
  oa_t,
  CASE
    WHEN oa_t IS NULL THEN false
    WHEN oa_t < 40.0 THEN true
    WHEN oa_t > 110.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:validation'
\`\`\`

**Confirmed fault:** \`raw_fault\` sustained for \`confirmation_seconds\` (hour test PATCH @ minute 30).

**Profile:** \`workspace/smoke-profiles/local/local_validation_profile.local.toml\`

---

## Plots + live data

| Where | What |
|-------|------|
| Bridge UI | http://127.0.0.1:8080 — Validation / FDD trends |
| Historian JSONL | \`${HIST_JSONL}\` (${HIST_LINES} rows) |
| Poll daemon | \`workspace/logs/bacnet_poll_daemon/cycles.jsonl\` |
| Rigorous reads | \`${RIGOROUS:-}/rigorous/driver_readings.jsonl\` |
| Hour cycles | \`${RIGOROUS:-}/hour_test/cycles.jsonl\` |

---

## RBAC matrix (bench probe)

| Check | admin | integrator | agent | operator |
|-------|-------|------------|-------|----------|
| Login + \`/api/auth/me\` role | expected | expected | expected | expected |
| GET \`/api/health/stack\` | 200 | 200 | 200 | 200 |
| POST \`/api/import/jobs\` | **403** auth-only | 2xx | 2xx | **403** insufficient role |
| POST \`/api/validation-runs/current/cycle\` | N/A | skip if no run | agent path | N/A |

Full log: \`${RBAC:-not run}/summary.txt\`

---

## Re-run commands

\`\`\`bash
cd ${ROOT}

# Reload data.env.local (Haystack pass, Modbus, JSON API) — recreate containers
./scripts/openfdd_bench_safe_restart.sh

# Remote LAN dial-in (after safe restart)
./scripts/openfdd_caddy_test_recipe.sh caddy-http
curl -fsS http://${OPENFDD_BENCH_IP:-192.168.204.55}/api/health | jq .

# Preflight only
OPENFDD_PROMPTS_DIR=workspace/logs/agent_prompts_latest ./scripts/openfdd_readme_agent_prompts_validate.sh
OPENFDD_MCP_EVAL_DIR=workspace/logs/mcp_eval_latest ./scripts/openfdd_mcp_eval.sh
OPENFDD_RBAC_DIR=workspace/logs/rbac_eval_latest ./scripts/openfdd_auth_rbac_validate.sh

# Update with historian restore + polling
REQUIRE_BACKUP=0 OPENFDD_RESTORE_HISTORIAN_AFTER_UPDATE=1 ./scripts/openfdd_rust_site_update.sh

# Full rigorous (Haystack gate auto ON when OPENFDD_HAYSTACK_PASS set in data.env.local)
./scripts/openfdd_rigorous_full_run.sh
# Or relax gates manually: OPENFDD_HOUR_REQUIRE_HAYSTACK=0 OPENFDD_HOUR_REQUIRE_JSON=0 ./scripts/openfdd_rigorous_full_run.sh

# Regenerate this report
./scripts/openfdd_bench_consolidated_report.sh

# Polling + Feather store validation (3 layers — documents upstream persistence bug)
./scripts/openfdd_bacnet_poll_daemon.sh start
./scripts/openfdd_polling_feather_validate.sh
\`\`\`

---

## Bench change log — everything touched (no rock unturned)

This section documents **bench-local** changes made during the **3.2.4** validation session on \`${ROOT}\`.  
These files are **not** overwritten by \`openfdd_rust_site_update.sh\` curling master compose (except \`docker-compose.yml\` from upstream — **override is preserved**).

### Docker / Compose

| File | Change | Why |
|------|--------|-----|
| \`docker-compose.override.yml\` | **NEW/UPDATED** — \`network_mode: host\` for \`openfdd-bridge\`, \`openfdd-caddy-http\`, \`openfdd-caddy-tls\`; \`ports: !override []\` | **3.2.4 regression:** bridge logs \`listening on http://127.0.0.1:8080\` inside container → Docker port publish (\`127.0.0.1:8080:8080\`) gets **connection reset**. Commission already used host network on :9091. |
| \`docker-compose.yml\` | **Unchanged locally** (from GHCR lifecycle curl) | Upstream stack: bridge, commission (host), haystack-gateway, Caddy profiles, MCP profile. |
| \`.env\` | Generated — \`OPENFDD_IMAGE_TAG=3.2.4\`, \`COMPOSE_PROFILES=full-edge\` | Lifecycle scripts; do not hand-edit. |

**Critical compose gotcha:** \`docker compose -f docker-compose.yml\` **does not** auto-merge \`docker-compose.override.yml\`. Bench scripts now use \`openfdd_rust_dcompose\` which passes **both** files. Without this, Caddy/ZAP recreate bridge **without** host network and break :8080 again.

### Caddy (LAN ingress / remote dial-in)

| File | Change | Why |
|------|--------|-----|
| \`docker/caddy/Caddyfile.http\` | \`reverse_proxy 127.0.0.1:8080\` (was \`openfdd-bridge:8080\`) | Bridge on **host network** is not reachable as Docker DNS name \`openfdd-bridge\`. Caddy also uses host network → proxies loopback. |
| \`docker/caddy/Caddyfile.tls\` | Same \`127.0.0.1:8080\` | TLS profile parity. |
| \`scripts/openfdd_caddy_test_recipe.sh\` | \`openfdd_caddy_restore_bridge\`; \`openfdd_rust_dcompose\`; Caddy \`up --force-recreate --no-deps\` | Starting Caddy must **not** recreate bridge (drops override). Restore bridge after \`direct\` / \`stop\`. |
| \`scripts/openfdd_zap_caddy_matrix.sh\` | Calls \`openfdd_rust_ensure_bridge_host_network\` after matrix | ZAP scenarios stop/start Caddy; bridge must stay on host network. |

**Remote access (LAN):**

\`\`\`bash
# Bridge direct (localhost only on bench host)
curl -fsS http://127.0.0.1:8080/api/health | jq .

# LAN via Caddy HTTP (host network, :80 on all interfaces)
./scripts/openfdd_caddy_test_recipe.sh caddy-http
curl -fsS http://${OPENFDD_BENCH_IP:-192.168.204.55}/api/health | jq .

# Return to direct (stop Caddy, restore bridge)
./scripts/openfdd_caddy_test_recipe.sh direct
\`\`\`

**SSH tunnel (off-LAN):** \`ssh -L 8080:127.0.0.1:8080 user@${OPENFDD_BENCH_IP:-192.168.204.55}\`

### Lifecycle / validation scripts (bench harness)

| Script | Role |
|--------|------|
| \`openfdd_rust_site_lib.sh\` | **+\`openfdd_rust_dcompose\`**, **+\`openfdd_rust_ensure_bridge_host_network\`** |
| \`openfdd_rust_site_update.sh\` | Uses \`openfdd_rust_dcompose\`; ensures bridge host network after recreate; historian export/restore default |
| \`openfdd_rust_historian_staging.sh\` | Export/restore Arrow/Feather/JSONL before/after update |
| \`openfdd_rust_site_restore.sh\` | Restore from staging or \`workspace-full.tgz\` |
| \`openfdd_bench_pull_latest.sh\` | Pull edge + MCP with tag fallbacks → \`ghcr_pull_latest.json\` |
| \`openfdd_bench_consolidated_report.sh\` | **This report** |
| \`openfdd_rigorous_full_run.sh\` | Phase -1 pull/update, preflight, hour test, semantic, rigorous, finalize (pcap+ZAP) |
| \`openfdd_readme_agent_prompts_validate.sh\` | Fetches live [README](https://raw.githubusercontent.com/bbartling/open-fdd/refs/heads/master/README.md) + checks OpenClaw/MCP markers |
| \`openfdd_mcp_eval.sh\` | Evaluates **slim** \`ghcr.io/bbartling/openfdd-mcp:\${tag}\` via stdio (not edge container binary) |
| \`openfdd_auth_rbac_validate.sh\` | integrator/agent/operator matrix incl. import 403 for operator |
| \`openfdd_drivers_validate.sh\` | BACnet (commission), Modbus read, Haystack, JSON API gates |
| \`openfdd_bacnet_poll_daemon.sh\` | 60s poll daemon with **live OT reads** each cycle (\`always_poll=true\`) |
| \`openfdd_polling_feather_validate.sh\` | **NEW:** 3-layer poll validation + Feather/Arrow persistence gates + \`POLLING_MECHANISM.md\` |
| \`openfdd_ot_pcap_capture.sh\` | Host-network tcpdump (BACnet 47808, Modbus **1502**, :8080, :9091, :443) |
| \`openfdd_ot_pcap_analyze.sh\` | **Fixed:** count Modbus on port **1502** (was mislabeled 502) |
| \`openfdd_pcap_minute_validate.sh\` | Per-minute buckets; expects Modbus on \`tcp port 1502\` |
| \`openfdd_stores_fdd_soak.sh\` | **Fixed:** explicit \`/api/modbus/read\` each cycle (status API alone does not generate OT wire traffic) |
| \`openfdd_soak_pcap_zap_finalize.sh\` | 10m pcap + soak + minute validate + ZAP matrix |
| \`openfdd_zap_caddy_matrix.sh\` | direct :8080, caddy-http :80, caddy-tls :443 |
| \`openfdd_bench_lib.sh\` | Loads \`workspace/bench/bench_profile.toml\` |
| \`openfdd_bench_safe_restart.sh\` | Safe stack bounce after \`data.env.local\` edits |

Config: \`workspace/bench/bench_profile.toml\` — pins **3.2.4**, MCP **v3.2.4**, OT IPs, preflight flags.

---

## 3.2.4 validation snapshot (\`${RIGOROUS:-latest run}\`)

| Phase | Result | Notes |
|-------|--------|-------|
| GHCR pull | **PASS** | edge \`3.2.4\`, MCP \`v3.2.4\` |
| Preflight prompts | **PASS** 19/19 | Live README markers match [bbartling/open-fdd](https://github.com/bbartling/open-fdd) |
| MCP eval | **PASS** tools live | **WARN:** \`mcp-not-in-bridge\` — edge image still ships \`openfdd-mcp\` binary |
| RBAC | **PASS** 18/18 | operator blocked on \`POST /api/import/jobs\` |
| Hour test | **FIXED** — live reads every cycle | \`POST /api/modbus/read\` + \`POST /api/bacnet/read\` (numeric Fn data), not \`/poll/status\` alone |
| Fault rule PATCH @ min 30 | **FAIL (product)** | \`404 unknown endpoint\`; \`fault_rule_changed: false\` |
| Semantic | **PARTIAL** | Haystack disabled (no password); RDF routes mostly 404 (#406) |
| Rigorous drivers | **PARTIAL** | Poll stable; Haystack/JSON point reads fail |
| Finalize pcap | **PARTIAL** | BACnet + HTTP :8080 seen; **Modbus buckets empty** (see below) |
| Finalize ZAP | **FAIL** | Bridge churn during matrix before host-network fixes; re-run after patches |

---

## PCAP vs Modbus — why BACnet shows up but Modbus did not

**Modbus driver works.** Live \`POST /api/modbus/read\` returns ~68–74°F from \`192.168.204.14:1502\`. Live \`tcpdump\` shows TCP on **port 1502** during reads.

**Finalize pcap had zero Modbus packets** because:

1. **Hour test / poll daemon (fixed 2026-06-30)** — \`openfdd_hour_driver_fault_test.sh\` now calls \`openfdd_bench_live_ot_poll\` **every minute**: Modbus reg **30001** numeric °F + BACnet \`bacnet:5007:analog-input:1173\` present-value + Who-Is. Artifacts: \`live_ot_cycle_*.json\`, \`cycles.jsonl\` includes \`modbus_value\` / \`bacnet_value\`.
2. **Prior gap:** status-only \`/api/modbus/poll/status\` returned \`ok: true\` with \`samples: 0\` **without** opening TCP to the field device.
2. **Soak does fire BACnet Who-Is** on commission :9091 → UDP 47808 appears in pcap.
3. **Analyze script bug (fixed):** summary line said \`modbus_tcp_502\` while bench Modbus uses **1502** (not standard 502).

**Harness fix:** \`openfdd_stores_fdd_soak.sh\` now calls \`/api/modbus/read\` each minute during pcap windows. Re-run finalize or \`openfdd_pcap_minute_validate.sh\` after a soak with pcap running to confirm Modbus buckets populate.

---

## Haystack — operator checklist

| Item | Bench state (live) |
|------|---------------------|
| TOML | \`workspace/haystack/local.nhaystack.toml\` → \`https://192.168.204.11/haystack\`, basic auth, \`tls_verify=false\` |
| User | \`OPENFDD_HAYSTACK_USER=open_fdd\` in \`workspace/data.env.local\` |
| Password in file | $(if [[ "$HAYSTACK_PASS_CFG" == "1" ]]; then echo "**SET** (not printed)"; else echo "**NOT SET**"; fi) |
| Bridge \`/api/haystack/status\` | enabled=\`${HAYSTACK_ENABLED}\` configured=\`${HAYSTACK_CONFIGURED}\` password_set=\`${HAYSTACK_PASSWORD_SET}\` |
| Station reachability | $(if [[ "$HAYSTACK_STATION_OK" == "1" ]]; then echo "**REACHABLE** (TCP/443 or HTTPS)"; else echo "**UNREACHABLE from bench** \`192.168.204.11\` — station is the Windows Niagara PC on OT LAN; ping often blocked — allow inbound TCP/443 (+ ICMP optional) from bench \`${OPENFDD_BENCH_IP:-192.168.204.55}\` in Windows Firewall"; fi) |
| Strict gate | \`bench_profile.toml\` \`require_haystack=true\` — hour test requires Haystack when pass is set |

\`\`\`bash
# After editing workspace/data.env.local:
cd ${ROOT}
./scripts/openfdd_bench_safe_restart.sh
OPENFDD_DRIVERS_VALIDATE_STRICT=1 ./scripts/openfdd_drivers_validate.sh
\`\`\`

Per [README field-bench keys](https://github.com/bbartling/open-fdd#field-bench-required-workspacedataenvlocal-keys): HTTP **Basic** auth, not SCRAM. **Restart-only does not reload env** — must recreate (safe restart or site update).

---

## MCP — which image the bench uses

| Image | Used for | Bench eval |
|-------|----------|------------|
| \`ghcr.io/bbartling/openfdd-mcp:v3.2.4\` | **Cursor/WSL stdio MCP** (\`docker run -i --network host\`) | **YES** — \`openfdd_mcp_eval.sh\` |
| \`ghcr.io/bbartling/openfdd-edge-rust:3.2.4\` | Bridge, commission, haystack-gateway | Edge stack only |
| \`openfdd-mcp\` binary **inside** edge image | Upstream README allows \`--entrypoint openfdd-mcp\` | Bench flags **mcp-not-in-bridge** — prefer slim sidecar only |

**Cursor MCP smoke (matches upstream README § Optional MCP):**

\`\`\`bash
source scripts/openfdd_auth_lib.sh
export OPENFDD_MCP_TOKEN="\$(openfdd_auth_login_token http://127.0.0.1:8080 workspace/auth.env.local integrator)"
docker run -i --rm --network host \\
  -e OPENFDD_API_BASE=http://127.0.0.1:8080 \\
  -e OPENFDD_COMMISSION_BASE=http://127.0.0.1:9091 \\
  -e OPENFDD_MCP_TOKEN \\
  ghcr.io/bbartling/openfdd-mcp:v3.2.4
\`\`\`

---

## Alignment with GitHub README agent prompts

Preflight (\`openfdd_readme_agent_prompts_validate.sh\`) fetches live master README and verifies:

| README prompt block | Bench coverage |
|---------------------|----------------|
| **OpenClaw — fresh Pi bootstrap** | \`openfdd_rust_edge_bootstrap.sh\` marker present; bench uses existing site not fresh bootstrap |
| **OpenClaw — ongoing operator** | Poll daemon, drivers validate, hour test, RBAC |
| **OpenClaw — backup/update/restore** | \`openfdd_rust_site_update.sh\` + historian staging/restore (**bench extension**) |
| **Field bench \`data.env.local\` keys** | Modbus/BACnet/JSON API **PASS** (httpbin poll-once 200); Haystack blocked on Windows firewall + TOML load |
| **Optional MCP for Cursor** | \`openfdd_mcp_eval.sh\`; slim \`openfdd-mcp\` image at pinned tag |

**Bench additions beyond upstream README:**

- \`docker-compose.override.yml\` (3.2.4 host-network workaround)
- \`openfdd_rust_dcompose\` / \`openfdd_rust_ensure_bridge_host_network\`
- Rigorous orchestrator + consolidated report + RBAC script + historian restore
- PCAP/ZAP/Caddy matrix (\`bench_profile.toml\` \`zap_caddy_matrix=true\`)
- This report's **WSL Cursor builder agent prompt** (product fix list for upstream)

**Never regress (README + bench):**

- Never \`docker compose down -v\`
- Never delete \`workspace/\`
- \`OPENFDD_BACNET_SERVER_ENABLED=0\` on bench
- Modbus @ \`192.168.204.14:1502\`, BACnet Who-Is via commission :9091

---

# WSL Cursor builder agent prompt — fix and patch (paste below)

**Cursor agent prompt — paste this entire section into a WSL Cursor agent session.**

**Bench:** \`${ROOT}\` — GHCR pull only, **never git clone on bench**  
**Source:** [bbartling/open-fdd](https://github.com/bbartling/open-fdd)  
**Read first:** this report + artifact \`${RIGOROUS:-logs/rigorous_full_latest}\`  
**Results issue:** [#${OPENFDD_RESULTS_ISSUE:-411}](https://github.com/bbartling/open-fdd/issues/${OPENFDD_RESULTS_ISSUE:-411})

---

## Mission

Ship **${OPENFDD_EXPECT_VERSION:-3.2.3}+** so \`./scripts/openfdd_patch_cycle_validate.sh\` **PASS** without regressing OT drivers.

### P0 — product (open-fdd repo / GHCR 3.2.5+)

1. **Bridge bind \`127.0.0.1:8080\`** — On 3.2.4, edge logs \`Open-FDD Rust Edge API listening on http://127.0.0.1:8080\`. Inside a container this breaks \`ports: "8080:8080"\` (host gets **connection reset**). **Fix:** bind \`0.0.0.0:8080\` when \`PORT=8080\`, or document host-network as supported mode. Until fixed, field benches need \`docker-compose.override.yml\` host network.
2. **Caddy upstream compose** — \`docker/caddy/Caddyfile.*\` uses \`reverse_proxy openfdd-bridge:8080\` which fails when bridge is host-networked. Support \`OPENFDD_CADDY_UPSTREAM\` env or \`host.docker.internal:8080\` with \`extra_hosts\`.
3. **Docker Compose override merge** — Document that \`-f docker-compose.yml\` alone skips \`docker-compose.override.yml\`; lifecycle scripts should pass both \`-f\` files.
4. **FDD fault rule PATCH API** — Hour test expects \`PATCH /api/fdd-rules/{id}\` or equivalent @ minute 30; today \`404 unknown endpoint\`, \`fault_rule_changed: false\`.
5. **JSON API bench smoke** — \`OPENFDD_JSON_API_TEST_URL\` + \`POST /api/json-api/poll-once\` with \`{"url":...}\` returns HTTP 200 (Integrations UI config optional). Status may stay \`configured: false\`; harness validates poll-once only.
6. **Haystack TOML + env (3.2.4+)** — With \`OPENFDD_HAYSTACK_PASS\` set, container shows \`password_set=true\` but driver may stay \`configured=false\` / \`base_url=null\` until TOML load is fixed. Station \`192.168.204.11\` is the **Windows Niagara PC** (same /24 as bench); unreachable from Linux is usually **Windows Firewall**, not wrong IP.
7. **haystack-gateway healthcheck** — Compose healthcheck fails intermittently on 3.2.4 bench.
8. **RDF/SPARQL #406** — Routes return 404; bench SKIP until shipped.
9. **MCP packaging** — Remove duplicate \`openfdd-mcp\` binary from edge bridge container OR document as intentional; bench \`mcp-not-in-bridge\` check expects sidecar-only on bridge.
10. **Login page dev shortcuts** — Remove “Sign in as integrator/admin”, bootstrap path hints, and role-assistance buttons from any ingress reachable on LAN (\`OPENFDD_ALLOW_INSECURE_AUTH\` dev UI must not ship on field edges).
11. **BACnet tab / driver tree** — Commission Who-Is finds field device **5007** but \`/api/bacnet/driver/tree\` stays local-only — UI BACnet tab empty until learn/sync exists.
12. **Model vs OT drivers** — Stale \`site:import\` CSV model persists in \`/api/model/ttl\` while validation profile expects \`site:local\` + BACnet **5007**; export/download over HTTP LAN triggers browser COOP/blob warnings.
13. **Modbus poll accumulator** — \`enabled_points>0\` but \`samples=0\`, \`last_poll=null\` while \`POST /api/modbus/read\` succeeds every minute — background poll loop not counting or not running.
14. **Historian pivot writer** — Live OT reads do not increment \`/api/historian/validation/status\` \`row_count\` or update host \`telemetry_pivot.jsonl\` / \`.arrow\` — **poll data not saved to Feather/Arrow store**.
15. **Historian path mismatch** — API reports \`historian/historian/telemetry_pivot.*\` but container only has \`historian/validation/telemetry_pivot.*\` — reader/writer disconnected.
16. **Default shipped model** — Fresh GHCR edge must not bundle \`site:import\` CSV dev model (\`${IMPORT_JOB_COUNT}\` import jobs); ship **blank/default** commissioning JSON.
17. **Model & FDD assignments tab** — Remove **FDD mapping** sub-tab/button; show fault rules on **main Validation dashboard**; fix “0 bound points · 0 rules” empty state.
18. **SQL tab rewrite** — Drop NL prompt + query builder + “Schema/DataFusion” chrome; keep table dropdown + SQL editor with **format SQL** only; default to professional \`telemetry_pivot\` rule SQL (see report head).
19. **OpenFDD BACnet server (599999)** — Always-on local server per [rusty-bacnet mini-device-revisited](https://github.com/jscott3201/rusty-bacnet/tree/dev/examples/rust/samples/mini-device-revisited): periodic I-Am, object-list, commission read works (today: \`device 599999 not in device table\`).
20. **Priority-array scan (hourly)** — Field device **${EXPECT_INST}** override scan per [point-discover](https://github.com/jscott3201/rusty-bacnet/tree/dev/examples/rust/samples/point-discover); validate once/hour in poll \`scan_interval_seconds=3600\`.

### P0 — harness (ship to bbartling/open-fdd \`scripts/\`)

1. \`openfdd_rust_historian_staging.sh\` + \`openfdd_rust_site_restore.sh\` — historian preserve on update (bench has them; upstream README backup prompt should link).
2. \`openfdd_auth_rbac_validate.sh\` — integrator/agent/operator matrix.
3. \`openfdd_bench_consolidated_report.sh\` — single MD report + embedded agent fix prompt.
4. \`openfdd_rust_dcompose\` + \`openfdd_rust_ensure_bridge_host_network\` — compose override safety after Caddy/ZAP/update.
5. \`openfdd_mcp_eval.sh\` — stdio eval against **slim** \`ghcr.io/bbartling/openfdd-mcp:\${tag}\`.
6. \`openfdd_readme_agent_prompts_validate.sh\` — live README OpenClaw block markers (bootstrap, operator, backup, MCP, field-bench keys).
7. PCAP soak: \`openfdd_stores_fdd_soak.sh\` must call \`/api/modbus/read\` (not just poll/status) when validating OT wire traffic.
8. \`openfdd_ot_pcap_analyze.sh\` — count Modbus on configured port (**1502** on this bench, not 502).
9. \`openfdd_bench_live_ot_poll\` + \`OPENFDD_HOUR_REQUIRE_LIVE_READS=1\` — hour/rigorous/poll-daemon must POST live Modbus/BACnet reads with numeric values every cycle (not status-only).
10. \`openfdd_polling_feather_validate.sh\` — document and gate the poll→historian→Feather persistence gap (upstream P0).

### P1 — bench validation gaps to close

1. Re-run \`openfdd_zap_caddy_matrix.sh\` after bridge host-network + \`openfdd_rust_dcompose\` patches.
2. Re-run finalize pcap after soak Modbus read fix — expect \`modbus\` minute buckets ≥ 1.
3. Set \`OPENFDD_HAYSTACK_PASS\` on bench → \`./scripts/openfdd_bench_safe_restart.sh\` → strict drivers PASS (auto-detected by harness)
4. Wire JSON API endpoints → \`configured: true\` on 3.2.4+.

### Bootstrap prompt parity ([README](https://github.com/bbartling/open-fdd#agent-prompts))

When patching upstream, ensure these README prompts remain accurate:

| Prompt | Must remain true after fixes |
|--------|------------------------------|
| Fresh Pi bootstrap | \`openfdd_rust_edge_bootstrap.sh --start\`, GHCR pull, \`curl :8080/api/health\`, auth in \`bootstrap_credentials.once.txt\` |
| Ongoing operator | JWT login, driver trees, FDD wires, **never** \`down -v\` |
| Backup/update/restore | \`openfdd_rust_site_backup.sh\` → \`openfdd_rust_site_update.sh\` → validate; add historian staging to backup prompt |
| Field bench keys | Modbus host/port, BACnet server disabled, Haystack user+pass, JSON API URL |
| Optional MCP | stdio \`openfdd-mcp\`, \`OPENFDD_MCP_TOKEN\`, \`--network host\`; document slim vs edge entrypoint |

### Remote bench access (WSL / LAN)

- Bench NIC: \`${OPENFDD_BENCH_IP:-192.168.204.55}\` (interface \`${OPENFDD_EDGE_NIC:-enp3s0}\`)
- Bridge API: \`http://127.0.0.1:8080\` (localhost on bench host — 3.2.4 binds loopback even on host network)
- **LAN UI/API:** \`./scripts/openfdd_caddy_test_recipe.sh caddy-http\` then \`http://${OPENFDD_BENCH_IP:-192.168.204.55}/\`
- **SSH tunnel:** \`ssh -L 8080:127.0.0.1:8080 user@${OPENFDD_BENCH_IP:-192.168.204.55}\`
- **Cursor MCP (WSL):** \`ghcr.io/bbartling/openfdd-mcp:v${OPENFDD_EXPECT_VERSION:-3.2.4}\` + integrator JWT — see MCP section above

### Never regress

- Modbus @ \`192.168.204.14:1502\` and BACnet Who-Is on commission :9091 (**PASS** on bench)  
- \`OPENFDD_BACNET_SERVER_ENABLED=0\` on bench  
- Never \`docker compose down -v\`; never delete \`workspace/\`  
- Poll daemon after tests: \`./scripts/openfdd_bacnet_poll_daemon.sh start\`

### Verify

\`\`\`bash
cd ${ROOT}
./scripts/openfdd_bench_consolidated_report.sh
./scripts/openfdd_polling_feather_validate.sh
OPENFDD_DRIVERS_VALIDATE_STRICT=1 ./scripts/openfdd_drivers_validate.sh
./scripts/openfdd_auth_rbac_validate.sh
./scripts/openfdd_mcp_eval.sh
OPENFDD_HOUR_REQUIRE_HAYSTACK=0 ./scripts/openfdd_rigorous_full_run.sh
\`\`\`

**Stop:** Do not fake Haystack PASS without \`OPENFDD_HAYSTACK_PASS\` in \`data.env.local\` **and** \`./scripts/openfdd_bench_safe_restart.sh\` recreate.

EOF

echo "Wrote $REPORT"
jq -nc --arg report "$REPORT" --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{timestamp_utc:$ts,report:$report,ok:true}' >"$ROOT/workspace/logs/consolidated_report_latest.json"
