#!/usr/bin/env bash
# Config-driven bench helpers — load profile, discover devices/points from live APIs.
# Source from validation scripts; not executed directly.
set -euo pipefail

openfdd_bench_root_from_caller() {
  local caller="${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}"
  cd "$(dirname "$caller")/.." && pwd
}

openfdd_bench_profile_path() {
  local root="${1:-$(openfdd_bench_root_from_caller)}"
  if [[ -n "${OPENFDD_BENCH_PROFILE:-}" && -f "${OPENFDD_BENCH_PROFILE}" ]]; then
    printf '%s' "$OPENFDD_BENCH_PROFILE"
  elif [[ -f "$root/workspace/bench/bench_profile.toml" ]]; then
    printf '%s' "$root/workspace/bench/bench_profile.toml"
  elif [[ -f "$root/workspace/bench/bench_profile.toml.example" ]]; then
    printf '%s' "$root/workspace/bench/bench_profile.toml.example"
  else
    echo "ERROR: no bench profile (set OPENFDD_BENCH_PROFILE or create workspace/bench/bench_profile.toml)" >&2
    return 1
  fi
}

# Export OPENFDD_* from TOML (env overrides win).
openfdd_bench_load_profile() {
  local root="${1:-$(openfdd_bench_root_from_caller)}"
  local profile
  profile="$(openfdd_bench_profile_path "$root")" || return 1

  OPENFDD_BENCH_PROFILE="$profile"
  OPENFDD_BENCH_ROOT="$root"

  eval "$(python3 - "$profile" <<'PY'
import json, os, sys
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

path = sys.argv[1]
with open(path, "rb") as f:
    cfg = tomllib.load(f)

def emit(key, val):
    if val is None:
        return
    if isinstance(val, bool):
        print(f'export {key}={"1" if val else "0"}')
    elif isinstance(val, (int, float)):
        print(f'export {key}={val}')
    elif isinstance(val, str):
        esc = val.replace("'", "'\\''")
        print(f"export {key}='{esc}'")
    elif isinstance(val, list):
        print(f"export {key}='{json.dumps(val)}'")

site = cfg.get("site", {})
api = cfg.get("api", {})
expect = cfg.get("expect", {})
disc = cfg.get("discovery", {})
mcp = cfg.get("mcp", {})
sem = cfg.get("semantic", {})
wonky = cfg.get("wonky", {})
gh = cfg.get("github", {})
run = cfg.get("run", {})
images = cfg.get("images", {})

emit("OPENFDD_BENCH_NAME", site.get("name"))
emit("OPENFDD_BENCH_IP", site.get("bench_ip"))
emit("OPENFDD_EDGE_NIC", site.get("edge_nic"))

emit("OPENFDD_API_BASE", api.get("bridge"))
emit("OPENFDD_COMMISSION_BASE", api.get("commission"))
emit("OPENFDD_MCP_HTTP", api.get("mcp_http"))

emit("OPENFDD_GITHUB_REPO", gh.get("repo", "bbartling/open-fdd"))
if gh.get("results_issue") and not os.environ.get("OPENFDD_RESULTS_ISSUE"):
    ri = gh.get("results_issue")
    if ri and int(ri) > 0:
        emit("OPENFDD_RESULTS_ISSUE", ri)
emit("OPENFDD_README_RAW_URL", gh.get("readme_raw"))
emit("OPENFDD_MCP_README_RAW_URL", gh.get("mcp_readme_raw"))

emit("OPENFDD_RUST_GHCR_IMAGE", images.get("edge", "ghcr.io/bbartling/openfdd-edge-rust"))
emit("OPENFDD_MCP_GHCR_IMAGE", images.get("mcp", "ghcr.io/bbartling/openfdd-mcp"))
edge_tag = images.get("edge_tag") or run.get("ghcr_edge_tag") or "nightly"
mcp_tag = images.get("mcp_tag") or run.get("ghcr_mcp_tag") or "nightly"
if not os.environ.get("OPENFDD_IMAGE_TAG"):
    emit("OPENFDD_IMAGE_TAG", edge_tag)
if not os.environ.get("OPENFDD_GHCR_TAG"):
    emit("OPENFDD_GHCR_TAG", edge_tag)
if not os.environ.get("OPENFDD_MCP_GHCR_TAG"):
    emit("OPENFDD_MCP_GHCR_TAG", mcp_tag)

emit("OPENFDD_DRIVER_POLL_INTERVAL_SEC", run.get("driver_poll_interval_sec", 60))
emit("OPENFDD_HOUR_TEST_MINUTES", run.get("hour_test_minutes", 60))
emit("OPENFDD_FAULT_RULE_CHANGE_MINUTE", run.get("fault_rule_change_minute", 30))
emit("OPENFDD_FAULT_RULE_ID", run.get("fault_rule_id", "oa_temp_out_of_range"))
emit("OPENFDD_JSON_API_VALIDATE_ONCE", "1" if run.get("json_api_validate_once", True) else "0")
if run.get("hour_require_live_reads") is not None and not os.environ.get("OPENFDD_HOUR_REQUIRE_LIVE_READS"):
    emit("OPENFDD_HOUR_REQUIRE_LIVE_READS", "1" if run.get("hour_require_live_reads") else "0")
emit("OPENFDD_RESTART_ON_FAIL", "1" if run.get("restart_on_fail", True) else "0")
emit("OPENFDD_MAX_RESTARTS", run.get("max_restarts", 2))
emit("OPENFDD_WAIT_FOR_GHCR", "1" if run.get("wait_for_ghcr", False) else "0")
emit("OPENFDD_ALWAYS_POLL", "1" if run.get("always_poll", True) else "0")
emit("OPENFDD_BACNET_DAEMON_MAX_CYCLES", run.get("poll_max_cycles", 5))
emit("OPENFDD_RESTORE_HISTORIAN_AFTER_UPDATE", "1" if run.get("restore_historian_after_update", True) else "0")
emit("OPENFDD_RUN_PREFLIGHT", "1" if run.get("run_preflight", True) else "0")
emit("OPENFDD_ZAP_CADDY_MATRIX", "1" if run.get("zap_caddy_matrix", False) else "0")

if expect.get("version") and not os.environ.get("OPENFDD_EXPECT_VERSION"):
    emit("OPENFDD_EXPECT_VERSION", expect.get("version"))
if expect.get("require_haystack") is not None and not os.environ.get("OPENFDD_REQUIRE_HAYSTACK"):
    emit("OPENFDD_REQUIRE_HAYSTACK", "1" if expect.get("require_haystack") else "0")

emit("OPENFDD_BACNET_WHOIS_LOW", disc.get("bacnet_whois_low", 0))
emit("OPENFDD_BACNET_WHOIS_HIGH", disc.get("bacnet_whois_high", 4194303))
emit("OPENFDD_BACNET_EXCLUDE_INSTANCES", json.dumps(disc.get("bacnet_exclude_local_instances", [599999])))
emit("OPENFDD_BACNET_MIN_FIELD_DEVICES", disc.get("bacnet_min_field_devices", 1))
emit("OPENFDD_BACNET_MIN_READ_POINTS", disc.get("bacnet_min_read_points", 2))
emit("OPENFDD_MODBUS_MIN_READ_POINTS", disc.get("modbus_min_read_points", 2))
emit("OPENFDD_HAYSTACK_MIN_CUR_POINTS", disc.get("haystack_min_cur_points", 3))
emit("OPENFDD_MODEL_MIN_ROWS", disc.get("model_min_rows", 1))
emit("OPENFDD_JSON_API_MIN_OK", disc.get("json_api_min_ok_sources", 1))
emit("OPENFDD_PCAP_OT_HOSTS", json.dumps(disc.get("pcap_ot_hosts", [])))
emit("OPENFDD_PCAP_BENCH_IP", disc.get("pcap_bench_ip"))

emit("OPENFDD_MCP_BINARY", mcp.get("binary", "openfdd-mcp"))
emit("OPENFDD_MCP_READ_ONLY_DEFAULT", "1" if mcp.get("read_only_default", True) else "0")
emit("OPENFDD_MCP_EXPECT_TOOLS", json.dumps(mcp.get("tools", [])))
emit("OPENFDD_MCP_EXPECT_TRANSPORTS", json.dumps(mcp.get("transports", [])))
emit("OPENFDD_MCP_EXPECT_RESOURCES", json.dumps(mcp.get("resources", [])))

emit("OPENFDD_RDF_PROBE_PATHS", json.dumps(sem.get("rdf_probe_paths", [])))
emit("OPENFDD_WONKY_LOG_PATTERNS", json.dumps(wonky.get("log_error_patterns", [])))
PY
)" || {
    echo "ERROR: failed to parse bench profile $profile (need python3 + tomllib)" >&2
    return 1
  }

  export OPENFDD_BENCH_PROFILE OPENFDD_BENCH_ROOT
}

openfdd_bench_data_env_file() {
  local root="${1:-${OPENFDD_BENCH_ROOT:-$(openfdd_bench_root_from_caller)}}"
  if [[ -f "$root/workspace/data.env.local" ]]; then
    printf '%s' "$root/workspace/data.env.local"
  fi
}

# Read OPENFDD_JSON_API_TEST_URL or OPENFDD_JSON_API_URL from workspace/data.env.local.
openfdd_bench_json_api_test_url() {
  local root="${1:-${OPENFDD_BENCH_ROOT:-$(openfdd_bench_root_from_caller)}}"
  local env_file key val
  env_file="$(openfdd_bench_data_env_file "$root")" || return 1
  [[ -f "$env_file" ]] || return 1
  for key in OPENFDD_JSON_API_TEST_URL OPENFDD_JSON_API_URL; do
    val="$(grep -E "^[[:space:]]*${key}=" "$env_file" 2>/dev/null | head -1 \
      | sed -E "s/^[[:space:]]*${key}=//" | tr -d '\r' | sed -E 's/^["'\''](.*)["'\'']$/\1/')"
    [[ -n "$val" ]] || continue
    printf '%s' "$val"
    return 0
  done
  return 1
}

# JSON body for /api/json-api/poll-once (httpbin/postbin smoke — does not require Integrations UI).
openfdd_bench_json_api_poll_once_body() {
  local root="${1:-${OPENFDD_BENCH_ROOT:-$(openfdd_bench_root_from_caller)}}"
  local url source env_file
  url="$(openfdd_bench_json_api_test_url "$root" 2>/dev/null || true)"
  [[ -n "$url" ]] || return 1
  source="httpbin-health"
  env_file="$(openfdd_bench_data_env_file "$root" 2>/dev/null || true)"
  if [[ -f "$env_file" ]]; then
    source="$(grep -E '^[[:space:]]*OPENFDD_JSON_API_TEST_SOURCE=' "$env_file" 2>/dev/null | head -1 \
      | sed -E 's/^[[:space:]]*OPENFDD_JSON_API_TEST_SOURCE=//' | tr -d '\r' || true)"
    [[ -n "$source" ]] || source="httpbin-health"
  fi
  jq -nc --arg url "$url" --arg source "$source" '{url:$url,source:$source}'
}

# True when workspace/data.env.local has a non-empty, uncommented OPENFDD_HAYSTACK_PASS.
openfdd_bench_haystack_pass_configured() {
  local env_file
  env_file="$(openfdd_bench_data_env_file "${1:-}")" || return 1
  [[ -f "$env_file" ]] || return 1
  grep -qE '^[[:space:]]*OPENFDD_HAYSTACK_PASS=.+[^[:space:]]' "$env_file" 2>/dev/null
}

# Best-effort reachability of Haystack base_url host from TOML (TCP/443 or HTTPS probe).
# Windows Niagara stations often block ICMP — do not treat ping failure as unreachable.
openfdd_bench_haystack_station_reachable() {
  local root="${1:-${OPENFDD_BENCH_ROOT:-$(openfdd_bench_root_from_caller)}}"
  local toml host base_url
  toml="$root/workspace/haystack/local.nhaystack.toml"
  [[ -f "$toml" ]] || return 1
  base_url="$(grep -E '^[[:space:]]*base_url[[:space:]]*=' "$toml" 2>/dev/null | head -1 \
    | sed -E 's/^[[:space:]]*base_url[[:space:]]*=[[:space:]]*["'\'' ]?([^"'\'' ]+).*/\1/' | tr -d '\r')"
  host="$(sed -E 's|https?://([^/:]+).*|\1|' <<<"${base_url:-}")"
  [[ -n "$host" ]] || return 1
  ping -c 1 -W 2 "$host" >/dev/null 2>&1 && return 0
  nc -z -w 5 "$host" 443 >/dev/null 2>&1 && return 0
  if [[ -n "$base_url" ]]; then
    curl -k -sS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 10 "$base_url" 2>/dev/null \
      | grep -qE '^(2|3|401|403|404|405)' && return 0
  fi
  curl -k -sS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 10 "https://${host}/" 2>/dev/null \
    | grep -qE '^(2|3|401|403|404|405)'
}

# Set hour-test gates from bench profile + data.env.local unless caller already exported overrides.
openfdd_bench_apply_validation_gates() {
  local root="${1:-${OPENFDD_BENCH_ROOT:-$(openfdd_bench_root_from_caller)}}"
  if [[ -z "${OPENFDD_HOUR_REQUIRE_HAYSTACK:-}" ]]; then
    if openfdd_bench_haystack_pass_configured "$root"; then
      export OPENFDD_HOUR_REQUIRE_HAYSTACK="${OPENFDD_REQUIRE_HAYSTACK:-1}"
    else
      export OPENFDD_HOUR_REQUIRE_HAYSTACK=0
    fi
  fi
  if [[ -z "${OPENFDD_HOUR_REQUIRE_JSON:-}" ]]; then
    if grep -qE '^[[:space:]]*OPENFDD_JSON_API_(TEST_URL|URL)=' "$(openfdd_bench_data_env_file "$root" 2>/dev/null || echo /dev/null)" 2>/dev/null; then
      export OPENFDD_HOUR_REQUIRE_JSON=1
    else
      export OPENFDD_HOUR_REQUIRE_JSON=0
    fi
  fi
}

# Recreate edge containers so env_file changes in workspace/data.env.local take effect.
openfdd_bench_reload_data_env() {
  local root="${1:-${OPENFDD_BENCH_ROOT:-$(openfdd_bench_root_from_caller)}}"
  # shellcheck source=scripts/openfdd_rust_site_lib.sh
  source "$(dirname "${BASH_SOURCE[0]}")/openfdd_rust_site_lib.sh"
  export OPENFDD_COMPOSE_ROOT="$root"
  openfdd_rust_check_docker
  echo "==> Recreate edge stack (reload workspace/data.env.local — no down -v)"
  openfdd_rust_dcompose "$root" up -d --force-recreate \
    openfdd-bridge openfdd-commission openfdd-haystack-gateway
  openfdd_rust_ensure_bridge_host_network "$root" "http://127.0.0.1:8080/api/health" || true
  openfdd_rust_wait_for_health "http://127.0.0.1:8080/api/health" "${OPENFDD_HEALTH_TIMEOUT_SECS:-120}"
}

openfdd_bench_curl_tls() {
  local base="${1:-${OPENFDD_API_BASE:-http://127.0.0.1:8080}}"
  if [[ "$base" == https://* ]]; then
    echo -k
  fi
}

openfdd_bench_whois_json() {
  local low="${OPENFDD_BACNET_WHOIS_LOW:-0}"
  local high="${OPENFDD_BACNET_WHOIS_HIGH:-4194303}"
  jq -nc --argjson low "$low" --argjson high "$high" '{low_limit:$low,high_limit:$high}'
}

# Authenticated GET/POST; prints response body to stdout.
openfdd_bench_api() {
  local method="$1" base="$2" path="$3" token="$4" body="${5:-}"
  local tls=()
  read -ra tls <<< "$(openfdd_bench_curl_tls "$base")"
  if [[ -n "$body" ]]; then
    curl "${tls[@]}" -fsS -X "$method" \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      -d "$body" "${base}${path}" 2>/dev/null || echo '{}'
  else
    curl "${tls[@]}" -fsS -X "$method" \
      -H "Authorization: Bearer $token" \
      "${base}${path}" 2>/dev/null || echo '{}'
  fi
}

# Writes discovery JSON to stdout: field devices + sample read point_ids.
openfdd_bench_discover_bacnet() {
  local bridge="$1" commission="$2" token="$3"
  local tree whois exclude min_reads
  tree="$(openfdd_bench_api GET "$bridge" "/api/bacnet/driver/tree" "$token")"
  whois="$(openfdd_bench_api POST "$commission" "/api/bacnet/whois" "$token" "$(openfdd_bench_whois_json)")"
  exclude="${OPENFDD_BACNET_EXCLUDE_INSTANCES:-[599999]}"
  min_reads="${OPENFDD_BACNET_MIN_READ_POINTS:-2}"
  smoke_inst="$(openfdd_bench_smoke_device_instance "${OPENFDD_BENCH_ROOT:-}")"
  python3 - "$exclude" "$min_reads" "$tree" "$whois" "$smoke_inst" <<'PY'
import json, os, sys

exclude = set(json.loads(sys.argv[1]))
min_reads = int(sys.argv[2])
tree = json.loads(sys.argv[3])
whois_raw = json.loads(sys.argv[4])
smoke_inst = int(sys.argv[5]) if len(sys.argv) > 5 else 5007
if not isinstance(whois_raw, list):
    whois_raw = []

def inst(obj):
    oid = obj.get("object_identifier") or {}
    if isinstance(oid, dict) and oid.get("instance") is not None:
        v = oid.get("instance")
    else:
        v = obj.get("device_instance", obj.get("instance", 0))
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0

def is_local(dev):
    if dev.get("local_server"):
        return True
    return inst(dev) in exclude

devs = tree.get("devices") or []
field_devs = [d for d in devs if not is_local(d)]
whois_field = [w for w in whois_raw if inst(w) not in exclude]

read_points = []
seen = set()
for d in devs:
    if is_local(d):
        continue
    for p in d.get("points") or []:
        if p.get("local_server"):
            continue
        pid = p.get("point_id") or p.get("id") or ""
        if not str(pid).startswith("bacnet:"):
            continue
        if pid in seen:
            continue
        seen.add(pid)
        read_points.append({
            "point_id": pid,
            "name": p.get("name") or p.get("object_name") or "",
            "object_type": p.get("object_type") or "",
        })
        if len(read_points) >= min_reads:
            break
    if len(read_points) >= min_reads:
        break

if not read_points:
    for obj_inst, name in [(1173, "oa_t"), (1168, "oa_h")]:
        read_points.append({
            "point_id": f"bacnet:{smoke_inst}:analog-input:{obj_inst}",
            "name": name,
            "object_type": "analog-input",
        })
        if len(read_points) >= min_reads:
            break

devices = []
seen_inst = set()
for d in field_devs + whois_field:
    i = inst(d)
    if i in seen_inst:
        continue
    seen_inst.add(i)
    devices.append({
        "device_instance": i,
        "address": d.get("address") or d.get("ip") or "",
        "name": d.get("name") or d.get("label") or "",
    })

print(json.dumps({
    "field_device_count": len(devices),
    "whois_field_count": len(whois_field),
    "devices": devices,
    "read_points": read_points[:min_reads],
    "whois_raw_count": len(whois_raw),
}))
PY
}

openfdd_bench_discover_modbus() {
  local bridge="$1" token="$2"
  local tree min_reads
  min_reads="${OPENFDD_MODBUS_MIN_READ_POINTS:-2}"
  tree="$(openfdd_bench_api GET "$bridge" "/api/modbus/driver/tree" "$token")"
  jq -nc --argjson tree "$tree" --argjson min_reads "$min_reads" '
    ($tree.devices // []) as $devs |
    [$devs[]?.points[]? |
      select(.register_address != null) |
      {
        point_id: (.point_id // ("modbus:" + (.register_address|tostring))),
        register: .register_address,
        function: (.function // "input_register"),
        label: (.label // "")
      }
    ] | unique_by(.register) | .[:($min_reads|tonumber)] as $pts |
    {device_count: ($devs|length), read_points: $pts}
  '
}

openfdd_bench_discover_haystack() {
  local bridge="$1" token="$2"
  local tree status test
  tree="$(openfdd_bench_api GET "$bridge" "/api/haystack/driver/tree" "$token")"
  status="$(openfdd_bench_api GET "$bridge" "/api/haystack/status" "$token")"
  test="$(openfdd_bench_api POST "$bridge" "/api/haystack/test" "$token" '{}')"
  jq -nc \
    --argjson tree "$tree" \
    --argjson status "$status" \
    --argjson test "$test" \
    --argjson min "${OPENFDD_HAYSTACK_MIN_CUR_POINTS:-3}" \
    '
    ($tree.devices // $tree.haystack_devices // []) as $devs |
    [$devs[]?.points[]? |
      select(.point_id // .haystack_id // .id) |
      {point_id: (.point_id // .haystack_id // .id), label: (.label // .tags.dis // ""), curVal: (.curVal // .tags.curVal // null)}
    ] | .[:($min|tonumber)] as $pts |
    {
      enabled: ($status.enabled // $tree.enabled // false),
      test_ok: ($test.ok // false),
      point_count: ([$devs[]?.points[]?] | length),
      read_points: $pts,
      status: $status,
      test: $test
    }
  '
}

openfdd_bench_discover_model() {
  local bridge="$1" token="$2"
  local model sites ttl
  model="$(openfdd_bench_api GET "$bridge" "/api/model/haystack" "$token")"
  sites="$(openfdd_bench_api GET "$bridge" "/api/model/sites" "$token")"
  ttl="$(openfdd_bench_api GET "$bridge" "/api/model/ttl" "$token" 2>/dev/null || echo '')"
  jq -nc \
    --argjson model "$model" \
    --argjson sites "$sites" \
    --arg ttl "$ttl" \
    --argjson min "${OPENFDD_MODEL_MIN_ROWS:-1}" \
    --arg expect_inst "${OPENFDD_SMOKE_DEVICE_INSTANCE:-${OPENFDD_BACNET_EXPECT_DEVICE_INSTANCE:-5007}}" \
    '
    ($model.rows // []) as $rows |
    ($sites.active_site_id // "") as $active |
    ($ttl | if . == "" then false else (test("source:csv:import|site:import|equip:import")) end) as $csv_ttl |
    ([$rows[]?.id // empty | select(test("^point:import-"))] | length) as $csv_rows |
    ([$rows[]?.id // empty | select(test("bacnet|5007|site:local|equip:local"))] | length) as $ot_rows |
    {
      row_count: ($rows | length),
      col_count: (($model.cols // []) | length),
      has_equip: ([$rows[]? | select(.equip == "M" or has("equipRef"))] | length > 0),
      has_point: ([$rows[]? | select(.point == "M" or has("fddInput"))] | length > 0),
      sample_ids: ([$rows[]?.id // empty] | .[:5]),
      active_site_id: $active,
      csv_dev_model: ($active == "site:import" or $csv_ttl or (($csv_rows > 0) and ($ot_rows == 0))),
      ot_model_present: ($ot_rows > 0 or $active == "site:local"),
      expect_device_instance: ($expect_inst | tonumber? // 5007),
      ok: (if $active == "site:import" then false elif (($rows | length) < ($min|tonumber)) then false else true end)
    }
  '
}

# Bench OT model gate — fails when stale CSV import dev model is active instead of live BACnet/Modbus.
openfdd_bench_validate_model_ot() {
  local bridge="$1" token="$2"
  local disc tree
  disc="$(openfdd_bench_discover_model "$bridge" "$token")"
  tree="$(openfdd_bench_api GET "$bridge" "/api/bacnet/driver/tree" "$token")"
  jq -nc \
    --argjson disc "$disc" \
    --argjson tree "$tree" \
    --argjson expect "${OPENFDD_SMOKE_DEVICE_INSTANCE:-${OPENFDD_BACNET_EXPECT_DEVICE_INSTANCE:-5007}}" \
    '
    ($tree.devices // []) as $devs |
    ([$devs[] | select(.device_instance != 599999 and .address != "local")] | length) as $tree_field |
    {
      active_site_id: $disc.active_site_id,
      csv_dev_model: $disc.csv_dev_model,
      ot_model_present: $disc.ot_model_present,
      sample_ids: $disc.sample_ids,
      bacnet_tree_field_count: $tree_field,
      expect_device_instance: ($expect|tonumber),
      ok: (if $disc.csv_dev_model then false elif $disc.active_site_id == "site:import" then false else true end)
    }
  '
}

# Bench smoke device instance from data.env.local or profile default (5007).
openfdd_bench_smoke_device_instance() {
  local root="${1:-${OPENFDD_BENCH_ROOT:-$(openfdd_bench_root_from_caller)}}"
  local env_file val
  env_file="$(openfdd_bench_data_env_file "$root" 2>/dev/null || true)"
  if [[ -f "$env_file" ]]; then
    val="$(grep -E '^[[:space:]]*OPENFDD_SMOKE_DEVICE_INSTANCE=' "$env_file" 2>/dev/null | head -1 \
      | sed -E 's/^[[:space:]]*OPENFDD_SMOKE_DEVICE_INSTANCE=//' | tr -d '\r')"
    [[ -n "$val" ]] && printf '%s' "$val" && return 0
  fi
  printf '%s' "${OPENFDD_SMOKE_DEVICE_INSTANCE:-${OPENFDD_BACNET_EXPECT_DEVICE_INSTANCE:-5007}}"
}

# Default Modbus live-read body — register 30001 @ .14:1502 (bench OT sim).
openfdd_bench_modbus_live_read_body() {
  jq -nc '{register:30001,function:"input_register",scale:0.1,unit:"degF"}'
}

# Per-cycle live OT poll: Modbus numeric read + BACnet present-value read + Who-Is.
# Fails closed when value is null — status-only APIs are not sufficient.
openfdd_bench_live_ot_poll() {
  local bridge="$1" commission="$2" token="$3"
  local root="${4:-${OPENFDD_BENCH_ROOT:-$(openfdd_bench_root_from_caller)}}"
  local inst bacnet_pid modbus_resp bacnet_resp whois_resp modbus_body
  inst="$(openfdd_bench_smoke_device_instance "$root")"
  bacnet_pid="bacnet:${inst}:analog-input:1173"
  modbus_body="$(openfdd_bench_modbus_live_read_body)"
  modbus_resp="$(openfdd_bench_api POST "$bridge" "/api/modbus/read" "$token" "$modbus_body")"
  bacnet_resp="$(openfdd_bench_api POST "$commission" "/api/bacnet/read" "$token" \
    "$(jq -nc --arg pid "$bacnet_pid" '{point_id:$pid}')")"
  whois_resp="$(openfdd_bench_api POST "$commission" "/api/bacnet/whois" "$token" "$(openfdd_bench_whois_json)")"
  jq -nc \
    --argjson modbus "$modbus_resp" \
    --argjson bacnet "$bacnet_resp" \
    --argjson whois "$whois_resp" \
    --arg bacnet_pid "$bacnet_pid" \
    --argjson inst "$inst" \
    '
    def is_num(v):
      if v == null then false
      elif (v|type) == "number" then true
      else (v|tostring|test("^[0-9]+(\\.[0-9]+)?$"))
      end;
    ($modbus.ok == true and is_num($modbus.value)) as $modbus_ok |
    (($bacnet.error // null) == null and is_num($bacnet.value)) as $bacnet_ok |
    ($whois|type=="array" and ($whois|length)>0) as $whois_ok |
    {
      smoke_device_instance: $inst,
      modbus_read_ok: $modbus_ok,
      modbus_value: ($modbus.value // null),
      modbus_host: ($modbus.host // null),
      modbus_register: ($modbus.register // 30001),
      bacnet_read_ok: $bacnet_ok,
      bacnet_value: ($bacnet.value // null),
      bacnet_point_id: $bacnet_pid,
      bacnet_whois_ok: $whois_ok,
      ok: ($modbus_ok and $bacnet_ok and $whois_ok)
    }
    '
}

# Host path for historian pivot files (bench mount — may differ from API-reported container path).
openfdd_bench_historian_host_dir() {
  local root="${1:-${OPENFDD_BENCH_ROOT:-$(openfdd_bench_root_from_caller)}}"
  printf '%s' "${OPENFDD_HISTORIAN_HOST_PATH:-$root/workspace/data/historian/validation}"
}

# Snapshot historian API + on-disk Arrow/JSONL/Feather state (stdout JSON).
openfdd_bench_historian_store_snapshot() {
  local bridge="$1" token="$2"
  local root="${3:-${OPENFDD_BENCH_ROOT:-$(openfdd_bench_root_from_caller)}}"
  local hist_dir jsonl arrow feather api host_jsonl host_arrow host_feather
  hist_dir="$(openfdd_bench_historian_host_dir "$root")"
  jsonl="$hist_dir/telemetry_pivot.jsonl"
  arrow="$hist_dir/telemetry_pivot.arrow"
  api="$(openfdd_bench_api GET "$bridge" "/api/historian/validation/status" "$token")"
  host_jsonl="$jsonl"
  host_arrow="$arrow"
  host_feather="$(find "$root/workspace/data" -name '*.feather' 2>/dev/null | head -1 || true)"
  feather="${host_feather:-}"
  jq -nc \
    --argjson api "$api" \
    --arg host_dir "$hist_dir" \
    --arg host_jsonl "${host_jsonl:-}" \
    --arg host_arrow "${host_arrow:-}" \
    --arg host_feather "${feather:-}" \
    --argjson jsonl_lines "$( [[ -f "$jsonl" ]] && wc -l <"$jsonl" | tr -d ' ' || echo 0 )" \
    --argjson jsonl_bytes "$( [[ -f "$jsonl" ]] && wc -c <"$jsonl" | tr -d ' ' || echo 0 )" \
    --argjson arrow_bytes "$( [[ -f "$arrow" ]] && wc -c <"$arrow" | tr -d ' ' || echo 0 )" \
    --arg jsonl_mtime "$( [[ -f "$jsonl" ]] && stat -c '%Y' "$jsonl" 2>/dev/null || echo 0 )" \
    --arg arrow_mtime "$( [[ -f "$arrow" ]] && stat -c '%Y' "$arrow" 2>/dev/null || echo 0 )" \
    '
    ($api.jsonl // "") as $api_jsonl |
    ($api.arrow_ipc // "") as $api_arrow |
    {
      api_row_count: ($api.row_count // 0),
      api_last_sample_at: ($api.last_sample_at // null),
      api_jsonl_path: $api_jsonl,
      api_arrow_path: $api_arrow,
      api_ok: ($api.ok // false),
      host_dir: $host_dir,
      host_jsonl_path: $host_jsonl,
      host_arrow_path: $host_arrow,
      host_feather_path: (if $host_feather == "" then null else $host_feather end),
      host_jsonl_lines: $jsonl_lines,
      host_jsonl_bytes: $jsonl_bytes,
      host_arrow_bytes: $arrow_bytes,
      host_jsonl_mtime: ($jsonl_mtime|tonumber),
      host_arrow_mtime: ($arrow_mtime|tonumber),
      path_mismatch: (
        ($api_jsonl != "" and ($host_jsonl|endswith("validation/telemetry_pivot.jsonl")) and ($api_jsonl|test("historian/historian/")))
      ),
      feather_present: ($host_feather != "")
    }
    '
}

# Derive PCAP OT host list from discovery + profile hints.
openfdd_bench_pcap_ot_hosts() {
  local discovery_json="$1"
  local hosts="${OPENFDD_PCAP_OT_HOSTS:-[]}"
  jq -nc \
    --argjson discovery "$discovery_json" \
    --argjson hints "$hosts" \
    '
    ($hints | if length > 0 then . else
      [$discovery.devices[]? | .address // .ip // empty | select(. != "" and . != "local")]
    end | unique) as $h |
    {ot_hosts: $h, bench_ip: (env.OPENFDD_PCAP_BENCH_IP // "")}
    '
}

openfdd_bench_check_line() {
  local name="$1" ok="$2" detail="$3" log_file="${4:-}"
  if [[ -n "$log_file" ]]; then
    if [[ "$ok" == "pass" ]]; then
      echo "PASS  $name — $detail" | tee -a "$log_file"
    elif [[ "$ok" == "skip" ]]; then
      echo "SKIP  $name — $detail" | tee -a "$log_file"
    else
      echo "FAIL  $name — $detail" | tee -a "$log_file"
    fi
  else
    if [[ "$ok" == "pass" ]]; then
      echo "PASS  $name — $detail"
    elif [[ "$ok" == "skip" ]]; then
      echo "SKIP  $name — $detail"
    else
      echo "FAIL  $name — $detail"
    fi
  fi
}

openfdd_bench_free_disk_gb() {
  local avail_kb
  avail_kb="$(df --output=avail / | tail -1 | tr -d ' ')"
  echo $((avail_kb / 1024 / 1024))
}

openfdd_bench_require_free_disk_gb() {
  local min_gb="${1:?min gb}"
  local avail_gb
  avail_gb="$(openfdd_bench_free_disk_gb)"
  if [[ "$avail_gb" -lt "$min_gb ]]; then
    echo "ERROR: only ${avail_gb}GB free on / — need at least ${min_gb}GB." >&2
    return 1
  fi
}

openfdd_bench_require_local_build_allowed() {
  if [[ "${OPENFDD_ALLOW_LOCAL_BUILD:-0}" != "1" ]]; then
    echo "ERROR: local Docker Rust --build is disabled on this bench." >&2
    echo "  Pull GHCR: OPENFDD_IMAGE_TAG=nightly ./scripts/openfdd_bench_pull_latest.sh" >&2
    return 1
  fi
  openfdd_bench_require_free_disk_gb "${1:-12}"
}
