# Open-FDD Rust Edge 3.2.0

Rust-only Open-FDD edge: API, dashboard, historian, BACnet/Modbus/JSON/Haystack drivers, DataFusion SQL fault detection, JWT agent API, and safe Docker lifecycle scripts.

**3.2.0** wires live field-bus drivers in Rust:
- BACnet via [`rusty-bacnet`](https://github.com/jscott3201/rusty-bacnet) (device 5007 on MS/TP via router)
- Modbus/TCP via native Rust client (RPi temp sensor at `192.168.204.14:1502`)

No Python, bacpypes, or PyPI runtime on this line.

## Service shape

```text
openfdd-bridge             API + dashboard + historian
openfdd-commission         BACnet / Modbus / JSON API discover-read-poll
openfdd-haystack-gateway   Haystack read/nav/ops integration
MCP                         later
```

## Quick start

```bash
cp .env.example .env
./scripts/openfdd_edge_bootstrap.sh
```

Open:

```text
http://localhost:8080
```

Or run directly:

```bash
docker compose up --build
```

## Local Rust dev

```bash
cargo fmt --all
cargo test --workspace
cargo run -p open_fdd_edge_prototype
```

## Auth

Public:

```text
GET  /api/health
POST /api/auth/login
```

Login:

```bash
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"sub":"agent","role":"agent"}' | jq -r .access_token)"
```

Then:

```bash
curl -s http://127.0.0.1:8080/api/health/stack \
  -H "Authorization: Bearer $TOKEN" | jq .
```

## Main AI-drivable routes

```text
GET  /api/agent/manifest
GET  /api/agent/tools
GET  /api/building/checkin
GET  /api/health/stack
GET  /api/ops/stack
POST /api/ops/docker/update

POST /api/bacnet/whois
POST /api/bacnet/point-discovery
GET  /api/bacnet/driver/tree
POST /api/bacnet/overrides/scan-once

POST /api/modbus/scan
GET  /api/modbus/points

GET  /api/json-api/sources
POST /api/json-api/register
POST /api/json-api/poll-once

GET  /api/haystack/about
POST /api/haystack/read
POST /api/haystack/nav
POST /api/haystack/ops

GET  /api/arrow/demo
GET  /api/fdd/datafusion/demo
POST /api/fdd/run
GET  /api/rules
POST /api/rules/save
POST /api/rules/batch

POST /api/reports/rcx/plan
POST /api/reports/rcx/generate
GET  /api/reports/rcx/list
```


## Code layout

```text
edge/src/
  main.rs
  drivers/
    mod.rs
    bacnet.rs
    modbus.rs
    json_api.rs
    haystack.rs
  historian/
    mod.rs
    arrow_table.rs
  fdd/
    mod.rs
    datafusion_sql.rs
  model/
    mod.rs
```

Driver code and the FDD/DataFusion SQL facade are in the same Rust crate layout (**v3.2.0**). **Live BACnet** uses [`rusty-bacnet`](https://github.com/jscott3201/rusty-bacnet) v0.9. **Live Modbus** uses native Modbus/TCP reads in `modbus_live.rs` (validated against RPi `192.168.204.14:1502`). Set `OPENFDD_BACNET_MODE=simulated` and `OPENFDD_MODBUS_MODE=simulated` for CI; set `live` for OT LAN hardware.


## UI direction

The UI is now focused around a Niagara-style driver tree plus a small number of main work areas.

Driver tree:
- BACnet
- Modbus
- JSON API
- Haystack

Main tabs:
- Dashboard
- SQL FDD
- Plots
- Haystack
- CDL
- Wire Sheet

The old Rule Lab tab is intentionally removed. Fault rules belong in SQL FDD and are DataFusion SQL only. The data model is Haystack-first. Assignments and CDL algorithm bindings resolve through Haystack IDs so BACnet, Modbus, JSON API, and Haystack can all feed the same protocol-agnostic algorithms.

BACnet override parity:
- `GET /api/bacnet/overrides/status`
- `POST /api/bacnet/overrides/scan-once`

The dashboard and driver tree surface priority 8 overrides separately from non-priority-8 overrides.

## Security rules

- JWT Bearer required for operational APIs.
- Roles: `operator`, `integrator`, `agent`.
- `OPENFDD_JWT_SECRET` signs tokens.
- BACnet writes require `integrator` and `approved=true`.
- Prototype BACnet writes are dry-run only.
- Keep the edge API on LAN/Tailscale.
- Never run `docker compose down -v`.
- Never delete `workspace/`.
- Never print secrets.

## Niagara direction

Custom Niagara WebSockets are replaced by Project Haystack:

```text
Niagara / BAS server
→ Project Haystack read/nav/ops
→ Rust Haystack gateway
→ Open-FDD model + Arrow tables
→ DataFusion SQL FDD
```

## What got gutted

Removed from this Rust-only baseline:

```text
pyproject.toml
Python package/runtime
PyArrow/Pandas rules
Dash/Python report code
Python MCP implementation
legacy scripts that assume a Python virtualenv
```

The new base keeps the Open-FDD operating idea: local-first edge stack, agent-drivable API, safe Docker lifecycle, and vendor-neutral HVAC fault detection.

## AI assignment model

Everything is assignable by AI through Haystack IDs:

```text
driver refs
external refs
historian storage refs
fault equation inputs
DataFusion SQL rules
CDL algorithm inputs/outputs
```

API:

```text
GET  /api/model/assignments
POST /api/model/assignments/save
POST /api/model/assignments/resolve
GET  /api/model/algorithm-bindings
GET  /api/control/cdl/bindings
POST /api/control/cdl/bindings/save
```

This keeps algorithms protocol agnostic:

```text
BACnet
Modbus
JSON API
Haystack
```

can all drive the same CDL algorithm or DataFusion SQL fault equation through the Haystack assignment layer.

## Latest fix

- Fixed `/api/model/query` build error by removing the old `HAYSTACK_MODEL` constant reference and routing through `drivers::haystack::model_json()`.
- Frontend syntax checked with `node --check frontend/app.js`.

## BACnet OT NIC setup

For Ben's Linux test box, the default BACnet OT NIC is currently:

```text
OPENFDD_BACNET_IFACE=enp3s0
OPENFDD_BACNET_BIND=192.168.204.55/24:47808
```

Generate `.env` safely:

```bash
./scripts/openfdd_bacnet_nic_setup.sh
```

For live BACnet/IP broadcast testing on Linux, use host networking and set router/MS/TP env vars in `.env`:

```bash
OPENFDD_BACNET_MODE=live
OPENFDD_BACNET_ROUTER_IP=192.168.204.200
OPENFDD_BACNET_MSTP_NET=2000
OPENFDD_BACNET_DISCOVER_LOW=5007
OPENFDD_BACNET_DISCOVER_HIGH=5007

docker compose -f docker-compose.yml -f docker-compose.bacnet-live.yml --env-file .env up --build
```

The helper script does not change the NIC unless `OPENFDD_BACNET_CONFIGURE_NIC=1` or `--apply` is used.
