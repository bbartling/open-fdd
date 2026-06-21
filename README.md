# Open-FDD Rust Edge

Rust-only Open-FDD edge prototype: API, dashboard, historian, BACnet/Modbus/JSON/Haystack drivers, DataFusion SQL fault detection, JWT agent API, and safe Docker lifecycle scripts.

This branch intentionally removes the Python/PyPI project shape. The goal is a small Rust-first base that can later grow into production crates.

## Goals

Build a free, open-source, full AFDD platform that is secure, vendor-agnostic, and designed for IoT edge deployments in the smart-building world.

The platform should include smart-building IoT drivers and full support for algorithms through CDL and a knowledge graph. Everything should be assignable by AI through Haystack, including fault equations, data storage, external references, and algorithm inputs/outputs.

Algorithms must be protocol-agnostic across BACnet, Modbus, JSON APIs, and Haystack. A CDL algorithm should be able to use data from any driver as long as the points are mapped through the Haystack assignment layer.

The project should also include a community-based expression-rule cookbook for DataFusion SQL and use everything the Apache Arrow project has to offer under the hood.


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

Driver code and the FDD/DataFusion SQL facade are now present in the same Rust crate layout. The fast Docker prototype uses deterministic simulator-backed drivers so the API and UI are testable without field hardware. Production wiring can swap those facades to `rusty-bacnet`, `rusty-modbus`, `rusty-haystack`, Apache Arrow, and DataFusion without changing the external API shape.

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

## Tested Powershell on Windows

> Note: DELETE ME this is just to validate application compiles ok. 

Syntax/compile only:
```
docker run --rm rust:1.85-bookworm bash -c "ls -la /usr/local/cargo/bin && /usr/local/cargo/bin/cargo --version"

```

Compile tests without running:
```
docker run --rm `
  -v "$($PWD.Path):/work" `
  -w /work `
  rust:1.85-bookworm `
  bash -c "export PATH=/usr/local/cargo/bin:`$PATH && cargo --version && cargo check --workspace --all-targets"
```

Include formatting too
```
docker run --rm `
  -v "$($PWD.Path):/work" `
  -w /work `
  rust:1.85-bookworm `
  bash -c "export PATH=/usr/local/cargo/bin:`$PATH && cargo test --workspace --all-targets --no-run"
```


---

## License

MIT — see [LICENSE](LICENSE).