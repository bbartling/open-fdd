# Open-FDD Rust Edge

Turn-key Rust + React prototype that mirrors the Open-FDD edge split:

```text
openfdd-bridge             API + dashboard + historian
openfdd-commission         BACnet / Modbus / JSON API discover-read-poll
openfdd-haystack-gateway   Haystack read/nav/ops integration
MCP                         intentionally deferred
```

## Start on Docker Desktop

```bash
cp .env.example .env
./scripts/edge_bootstrap.sh
```

Open:

```text
http://localhost:8080
```

## Direct Docker command

```bash
docker compose up --build
```

## Auth

Public endpoints:

```text
GET  /api/health
POST /api/auth/login
```

JWT login:

```bash
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"sub":"agent","role":"agent"}' | jq -r .access_token)"
```

Use:

```bash
-H "Authorization: Bearer $TOKEN"
```

Roles:

```text
operator
integrator
agent
```

## Required Open-FDD-style endpoints now included

```text
POST /api/auth/login
GET  /api/health/stack
POST /api/rules/save
POST /api/rules/batch
POST /api/model/haystack/import
GET  /api/bacnet/driver/tree
POST /api/bacnet/overrides/scan-once
POST /api/reports/rcx/generate
GET  /api/agent/tools
```

## Driver/data APIs

```text
POST /api/bacnet/whois
POST /api/bacnet/point-discovery
GET  /api/bacnet/points
GET  /api/bacnet/driver/tree
POST /api/bacnet/driver/sync-discovery
POST /api/bacnet/read
POST /api/bacnet/write
GET  /api/bacnet/overrides/status
POST /api/bacnet/overrides/scan-once

GET  /api/modbus/points
POST /api/modbus/scan
POST /api/modbus/read

GET  /api/json-api/sources
POST /api/json-api/register
POST /api/json-api/poll-once

GET  /api/haystack/about
POST /api/haystack/read
POST /api/haystack/nav
POST /api/haystack/ops
GET  /api/model/haystack
POST /api/model/haystack/import
POST /api/model/query
```

## Algorithms / FDD / historian

```text
GET  /api/algorithms
POST /api/algorithms/run
GET  /api/arrow/demo
GET  /api/fdd/datafusion/demo
POST /api/fdd/run
GET  /api/rules
POST /api/rules/save
POST /api/rules/batch
GET  /api/historian/query
POST /api/historian/query
```

## Agent and lifecycle APIs

```text
GET  /api/agent/manifest
GET  /api/agent/tools
POST /api/agent/bootstrap
POST /api/agent/update
GET  /api/building/checkin
GET  /api/ops/stack
POST /api/ops/docker/update
POST /api/reports/rcx/plan
POST /api/reports/rcx/generate
GET  /api/reports/rcx/list
```

## Security posture

- `OPENFDD_JWT_SECRET` signs HS256 JWTs.
- Token TTL is 8 hours.
- Static UI and `/api/health` are public.
- All operational `/api/*` calls require Bearer JWT.
- BACnet write requires `integrator` role and `approved=true`.
- Prototype BACnet writes are dry-run only.
- Keep this edge stack on LAN/Tailscale.
- Never run `docker compose down -v`.
- Never delete `workspace/`.
- Never print secrets or auth files.

## Niagara integration direction

Custom Niagara WebSockets are intentionally replaced by the Haystack gateway path:

```text
Niagara / BAS server -> Project Haystack read/nav/ops -> Rust Haystack gateway -> Open-FDD model + Arrow tables
```

MCP/RAG sidecar comes later; this release is focused on full JSON/JWT agent drivability.

## Production Rust backend skeleton

`backend/` is the production integration direction with:

```text
rusty-bacnet
rusty-modbus
rusty-haystack
open-control-engine
Apache Arrow
DataFusion SQL
JWT auth module
```

The fast default container uses `edge_prototype_rust/` so Docker Desktop can start quickly.
