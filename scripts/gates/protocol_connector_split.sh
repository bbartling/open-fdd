#!/usr/bin/env bash
# Phase 5B process, image, and cloud topology gate.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "== gate: protocol connector split =="
cargo test -p openfdd-fieldbus --lib split::tests

SPLIT_TMP_DIR="${TMPDIR:-/tmp}/openfdd-protocol-split-$$"
SPLIT_CONFIG_DIR="$SPLIT_TMP_DIR/config"
mkdir -p "$SPLIT_CONFIG_DIR" "$SPLIT_TMP_DIR/kit" "$SPLIT_TMP_DIR/state"

# Use a synthetic, empty field-device catalog. The gate must not read the
# repository's demo/bench inventory or trigger discovery against an OT host.
cat >"$SPLIT_CONFIG_DIR/gateway.toml" <<'EOF'
[poll]
enabled = false
EOF
cat >"$SPLIT_CONFIG_DIR/objects.csv" <<'EOF'
Name,PointType,Units,Commandable,Default,Instance,Description
synthetic-read,AV,noUnits,N,0.0,9101,synthetic split process health object
EOF
cat >"$SPLIT_CONFIG_DIR/field_devices.toml" <<'EOF'
devices = []
EOF
cat >"$SPLIT_CONFIG_DIR/haystack-catalog.toml" <<'EOF'
revision = "synthetic-split-catalog-v1"

[[records]]
key = "synthetic-equipment"
kind = "equipment"
display_name = "Synthetic Equipment"
source_ref = "synthetic-equipment"

[[records]]
key = "synthetic-temperature"
kind = "point"
display_name = "Synthetic Temperature"
equipment_key = "synthetic-equipment"
role = "zone_t"
unit = "degF"
source_ref = "synthetic-temperature"
EOF

# Cloud recipes are intentionally IT-only. Check both source and resolved
# Compose so interpolation cannot reintroduce an OT image/process.
for recipe in docker/compose.central.yml docker/compose.csv.yml; do
  if rg -ni 'openfdd-(fieldbus|bacnet-modbus|haystack)|bacnet|modbus|haystack|47808|network_mode:[[:space:]]*host' "$recipe"; then
    echo "FAIL: cloud recipe contains an OT connector or BACnet socket: $recipe" >&2
    exit 1
  fi
  resolved="$SPLIT_TMP_DIR/$(basename "$recipe").resolved.yml"
  OPENFDD_SITE_ID=split-test \
  OPENFDD_EDGE_ID=split-edge \
  OPENFDD_EDGE_KIT_DIR="$SPLIT_TMP_DIR/kit" \
  OPENFDD_CONNECTOR_API_KEY=split-test-key \
  OPENFDD_HAYSTACK_BASE_URL=https://example.invalid \
  OPENFDD_MQTT_HOST=127.0.0.1 \
  OPENFDD_JWT_SECRET=split-test-jwt \
  OPENFDD_ADMIN_PASSWORD=split-test-admin \
    docker compose -f "$recipe" config >"$resolved"
  if rg -ni 'openfdd-(fieldbus|bacnet-modbus|haystack)|bacnet|modbus|haystack|47808|network_mode:[[:space:]]*host' "$resolved"; then
    echo "FAIL: resolved cloud recipe contains an OT connector or BACnet socket: $recipe" >&2
    exit 1
  fi
  echo "OK cloud-negative: $recipe"
done

for binary in openfdd-bacnet-modbus openfdd-haystack; do
  test -f "services/fieldbus/src/bin/$binary.rs"
  echo "OK entrypoint source: $binary"
done

# Build debug binaries for the local live management-plane checks.
cargo build -p openfdd-fieldbus --bin openfdd-bacnet-modbus --bin openfdd-haystack
TARGET_DIR="${CARGO_TARGET_DIR:-target}/debug"
SPLIT_PIDS=()

owned_socket_count() {
  local pid="$1"
  local count=0
  local fd link
  for fd in "/proc/$pid/fd/"*; do
    link="$(readlink "$fd" 2>/dev/null || true)"
    case "$link" in
      socket:\[*\]) count=$((count + 1)) ;;
    esac
  done
  printf '%s\n' "$count"
}

owned_udp_socket_count() {
  local pid="$1"
  local count=0
  local fd link inode
  for fd in "/proc/$pid/fd/"*; do
    link="$(readlink "$fd" 2>/dev/null || true)"
    case "$link" in
      socket:\[*\])
        inode="${link#socket:[}"
        inode="${inode%]}"
        if cat "/proc/$pid/net/udp" "/proc/$pid/net/udp6" 2>/dev/null \
          | awk -v wanted="$inode" 'NR > 1 && $10 == wanted { found = 1 } END { exit found ? 0 : 1 }'; then
          count=$((count + 1))
        fi
        ;;
    esac
  done
  printf '%s\n' "$count"
}

stop_split_processes() {
  local pid
  for pid in "${SPLIT_PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  done
}

cleanup_images() {
  stop_split_processes
  local image
  for image in "${SPLIT_IMAGES[@]-}"; do
    docker image rm -f "$image" >/dev/null 2>&1 || true
  done
}
SPLIT_IMAGES=()
trap cleanup_images EXIT

wait_for_health() {
  local pid="$1"
  local port="$2"
  local log="$3"
  for _ in $(seq 1 120); do
    kill -0 "$pid" 2>/dev/null || { cat "$log" >&2; exit 1; }
    if curl -fsS --max-time 1 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.1
  done
  cat "$log" >&2
  echo "management health did not become ready on port $port" >&2
  exit 1
}

assert_live_status() {
  local port="$1"
  local method="$2"
  local path="$3"
  local expected="$4"
  local actual
  actual="$(curl -sS --max-time 2 -o /dev/null -w '%{http_code}' \
    -X "$method" -H 'Authorization: Bearer split-test-key' \
    "http://127.0.0.1:$port$path")"
  test "$actual" = "$expected" || {
    echo "FAIL: $method $path on $port returned $actual, expected $expected" >&2
    exit 1
  }
}

bacnet_http_port="$(shuf -i 21000-28000 -n 1)"
bacnet_udp_port="$(shuf -i 30000-38000 -n 1)"
bacnet_log="$SPLIT_TMP_DIR/bacnet-modbus.log"
env -u HAYSTACK_BASE_URL -u OPENFDD_HAYSTACK_BASE_URL \
  -u HAYSTACK_USER -u OPENFDD_HAYSTACK_USER \
  -u HAYSTACK_PASS -u OPENFDD_HAYSTACK_PASS \
  OPENFDD_FIELDBUS_CONFIG_DIR="$SPLIT_CONFIG_DIR" \
  OPENFDD_FIELDBUS_HTTP_HOST=127.0.0.1 \
  OPENFDD_FIELDBUS_HTTP_PORT="$bacnet_http_port" \
  OPENFDD_FIELDBUS_BACNET_PORT="$bacnet_udp_port" \
  OPENFDD_FIELDBUS_SERVER_BIND=127.0.0.1 \
  OPENFDD_FIELDBUS_BIND=127.0.0.1 \
  OPENFDD_FIELDBUS_POLL_ENABLED=0 \
  OPENFDD_MQTT_ENABLED=0 \
  OPENFDD_EDGE_STORE_DIR="$SPLIT_TMP_DIR/state/bacnet" \
  OPENFDD_CONNECTOR_API_KEY=split-test-key \
    "$TARGET_DIR/openfdd-bacnet-modbus" >"$bacnet_log" 2>&1 &
bacnet_pid=$!
SPLIT_PIDS+=("$bacnet_pid")
wait_for_health "$bacnet_pid" "$bacnet_http_port" "$bacnet_log"
test "$(owned_udp_socket_count "$bacnet_pid")" -gt 0
echo "OK process-socket: openfdd-bacnet-modbus owns UDP"

bacnet_hello="$(curl -fsS -H 'Authorization: Bearer split-test-key' \
  "http://127.0.0.1:$bacnet_http_port/api/connector/hello")"
test "$(jq -r '.version.service' <<<"$bacnet_hello")" = openfdd-bacnet-modbus
test "$(jq -r '.service_identity.process_id' <<<"$bacnet_hello")" = "$bacnet_pid"

# The split BACnet process has a narrow, explicit allowlist. Its legacy root,
# /api BACnet aliases, write/discovery/Who-Is routes, compat aliases, weather,
# and arbitrary Modbus path must all be absent.
assert_live_status "$bacnet_http_port" GET / 404
for path in \
  /bacnet/write /bacnet/write-dry-run /bacnet/whois /bacnet/whois-router \
  /bacnet/supervisory /bacnet/server/update /api/bacnet/read \
  /api/bacnet/point-discovery /modbus/read /telemetry/suspend \
  /telemetry/resume /weather/refresh; do
  assert_live_status "$bacnet_http_port" POST "$path" 404
done
assert_live_status "$bacnet_http_port" GET /bacnet/poll/status 200
assert_live_status "$bacnet_http_port" GET /api/health 200
echo "OK live-routes: BACnet allowlist and prohibited paths"

haystack_http_port="$(shuf -i 28001-35000 -n 1)"
haystack_log="$SPLIT_TMP_DIR/haystack.log"
env -u HAYSTACK_USER -u OPENFDD_HAYSTACK_USER \
  -u HAYSTACK_PASS -u OPENFDD_HAYSTACK_PASS \
  OPENFDD_FIELDBUS_CONFIG_DIR="$SPLIT_CONFIG_DIR" \
  OPENFDD_FIELDBUS_HTTP_HOST=127.0.0.1 \
  OPENFDD_FIELDBUS_HTTP_PORT="$haystack_http_port" \
  OPENFDD_HAYSTACK_BASE_URL=https://example.invalid \
  OPENFDD_HAYSTACK_USER=split-synthetic-user \
  OPENFDD_HAYSTACK_PASS=split-synthetic-pass \
  OPENFDD_HAYSTACK_CATALOG_PATH="$SPLIT_CONFIG_DIR/haystack-catalog.toml" \
  OPENFDD_HAYSTACK_AUTH_MODE=basic \
  OPENFDD_CONNECTOR_API_KEY=split-test-key \
    "$TARGET_DIR/openfdd-haystack" >"$haystack_log" 2>&1 &
haystack_pid=$!
SPLIT_PIDS+=("$haystack_pid")
wait_for_health "$haystack_pid" "$haystack_http_port" "$haystack_log"
test "$(owned_udp_socket_count "$haystack_pid")" -eq 0
echo "OK process-socket: openfdd-haystack owns no UDP socket"

haystack_hello="$(curl -fsS -H 'Authorization: Bearer split-test-key' \
  "http://127.0.0.1:$haystack_http_port/api/connector/hello")"
test "$(jq -r '.version.service' <<<"$haystack_hello")" = openfdd-haystack
test "$(jq -r '.service_identity.process_id' <<<"$haystack_hello")" = "$haystack_pid"
test "$bacnet_pid" != "$haystack_pid"

for path in / /bacnet/whois /bacnet/whois-router /api/bacnet/read \
  /api/bacnet/point-discovery /modbus/read; do
  assert_live_status "$haystack_http_port" POST "$path" 404
done
assert_live_status "$haystack_http_port" GET /health 200
echo "OK live-routes: Haystack excludes BACnet/Modbus paths"

stop_split_processes
SPLIT_PIDS=()

# Build and inspect each final target. Every image must contain exactly its
# intended product executable, entrypoint, defaults, ports, and healthcheck.
for target in bacnet-modbus haystack compatibility; do
  image="openfdd-protocol-split-gate:${target}-$$"
  docker build --quiet --target "$target" -t "$image" -f services/fieldbus/Dockerfile . >/dev/null
  SPLIT_IMAGES+=("$image")
  case "$target" in
    bacnet-modbus)
      docker run --rm --entrypoint /bin/sh "$image" -ec \
        'test -x /usr/local/bin/openfdd-bacnet-modbus; ! test -e /usr/local/bin/openfdd-haystack; ! test -e /usr/local/bin/openfdd-fieldbus'
      docker image inspect "$image" | jq -e \
        '.[0].Config.Entrypoint == ["/usr/local/bin/openfdd-bacnet-modbus"] and
         (.[0].Config.Env | index("OPENFDD_FIELDBUS_HTTP_HOST=0.0.0.0")) != null and
         (.[0].Config.Env | index("OPENFDD_FIELDBUS_HTTP_PORT=8081")) != null and
         (.[0].Config.ExposedPorts | has("8081/tcp") and has("47808/udp")) and
         ((.[0].Config.Healthcheck.Test | join(" ")) | contains("8081/health"))' >/dev/null
      ;;
    haystack)
      docker run --rm --entrypoint /bin/sh "$image" -ec \
        'test -x /usr/local/bin/openfdd-haystack; ! test -e /usr/local/bin/openfdd-bacnet-modbus; ! test -e /usr/local/bin/openfdd-fieldbus; ! test -e /app/config'
      docker image inspect "$image" | jq -e \
        '.[0].Config.Entrypoint == ["/usr/local/bin/openfdd-haystack"] and
         (.[0].Config.Env | index("OPENFDD_FIELDBUS_HTTP_HOST=0.0.0.0")) != null and
         (.[0].Config.Env | index("OPENFDD_FIELDBUS_HTTP_PORT=8082")) != null and
         (.[0].Config.ExposedPorts | has("8082/tcp") and ((has("47808/udp")) | not)) and
         ((.[0].Config.Healthcheck.Test | join(" ")) | contains("8082/health"))' >/dev/null
      ;;
    compatibility)
      docker run --rm --entrypoint /bin/sh "$image" -ec \
        'test -x /usr/local/bin/openfdd-fieldbus; ! test -e /usr/local/bin/openfdd-bacnet-modbus; ! test -e /usr/local/bin/openfdd-haystack'
      docker image inspect "$image" | jq -e \
        '.[0].Config.Entrypoint == ["/usr/local/bin/openfdd-fieldbus"] and
         (.[0].Config.Env | index("OPENFDD_FIELDBUS_HTTP_HOST=127.0.0.1")) != null and
         (.[0].Config.ExposedPorts | has("8081/tcp") and has("47808/udp")) and
         ((.[0].Config.Healthcheck.Test | join(" ")) | contains("8081/health"))' >/dev/null
      ;;
  esac
  echo "OK image-target: $target"
done

# Resolve the edge recipe both with and without the optional Haystack profile.
# Use Compose's structured JSON output because the port mapping is represented
# as host_ip/target/published/protocol fields rather than a compact string.
default_compose="$SPLIT_TMP_DIR/edge.default.resolved.json"
profile_compose="$SPLIT_TMP_DIR/edge.haystack.resolved.json"
env -u OPENFDD_HAYSTACK_BASE_URL \
  OPENFDD_SITE_ID=split-test \
  OPENFDD_EDGE_KIT_DIR="$SPLIT_TMP_DIR/kit" \
  OPENFDD_CONNECTOR_API_KEY=split-test-key \
  docker compose -f docker/compose.edge.split.yml config --format json >"$default_compose"
OPENFDD_SITE_ID=split-test \
OPENFDD_EDGE_KIT_DIR="$SPLIT_TMP_DIR/kit" \
OPENFDD_CONNECTOR_API_KEY=split-test-key \
OPENFDD_HAYSTACK_BASE_URL=https://example.invalid \
  docker compose --profile haystack -f docker/compose.edge.split.yml config --format json >"$profile_compose"
jq -e '(.services | has("haystack") | not) and (.services["bacnet-modbus"].environment.OPENFDD_FIELDBUS_HTTP_HOST == "0.0.0.0")' \
  "$default_compose" >/dev/null
jq -e '
  .services.haystack.profiles == ["haystack"] and
  .services.haystack.environment.OPENFDD_FIELDBUS_HTTP_HOST == "0.0.0.0" and
  .services.haystack.environment.OPENFDD_HAYSTACK_BASE_URL == "https://example.invalid" and
  (.services.haystack.ports | any(.[];
    .host_ip == "127.0.0.1" and
    (.target | tonumber) == 8082 and
    (.published | tonumber) == 8082 and
    .protocol == "tcp"
  )) and
  ((.services.haystack.healthcheck.test | join(" ")) | contains("8082/health"))
' "$profile_compose" >/dev/null
echo "OK compose-config: docker/compose.edge.split.yml (default + haystack profile)"

echo "PASS: protocol connector split"
