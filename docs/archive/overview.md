# Architecture overview

Open-FDD uses **Apache Arrow** and **Feather** as the native historian and data storage layer, while **DataFusion SQL** serves as the fault detection and analytics engine that operates directly on those Arrow datasets. Rather than storing building telemetry in a traditional relational database, data collected from BACnet, Haystack, Modbus, and JSON APIs is normalized into Arrow-native structures and persisted as Feather files, allowing high-performance columnar analytics at the edge. DataFusion then executes SQL-based fault detection rules, reporting logic, and data quality checks directly against the Arrow historian — a clear path toward a fully Rust-based analytics stack without Pandas or other row-oriented processing frameworks.

The platform is migrating to an **all-Rust architecture**, including protocol drivers, historian services, APIs, and the analytics engine:

| Layer | Technology |
| --- | --- |
| BACnet | Rust-native BACnet (`rusty-bacnet` live path) |
| Haystack | Rust Haystack gateway (`openfdd-haystack-gateway`) |
| Modbus | Rust Modbus/TCP client (bridge service) |
| JSON API | HTTP source registration and poll-once (bridge service) |
| Historian | Apache Arrow RecordBatches → Feather persistence |
| FDD | DataFusion SQL + confirmation duration |
| UI | React static assets served by the bridge |
| Auth | JWT + RBAC on the bridge |

This keeps the telemetry pipeline memory-safe, performant, and suitable for resource-constrained edge devices as well as larger on-premises building servers.

## Docker edge stack

Open-FDD deploys as Docker containers that work together as a complete edge operations platform:

```text
┌─────────────────────────────────────────────────────────────────┐
│  openfdd-bridge (SERVICE_MODE=bridge, :8080)                    │
│  REST API · JWT auth · React dashboard · Arrow historian        │
│  Modbus driver · JSON API sources · DataFusion FDD · agent APIs │
└─────────────────────────────────────────────────────────────────┘
         │ shared workspace volume (workspace/)
         ▼
┌──────────────────────────┐  ┌──────────────────────────────────┐
│ openfdd-commission       │  │ openfdd-haystack-gateway         │
│ BACnet discover/poll/    │  │ Project Haystack read/nav/ops    │
│ override scan            │  │ (BAS / Niagara integration path) │
└──────────────────────────┘  └──────────────────────────────────┘
```

All three containers use the same GHCR image (`ghcr.io/bbartling/openfdd-edge-rust`) with different `SERVICE_MODE` values. Production deployments may add **Caddy** for TLS (`docker-compose.prod.yml`).

MCP and knowledge services are planned. Agent JSON APIs are already exposed by the bridge.

## Data flow

```text
Field buses (BACnet / Modbus / JSON / Haystack)
  → driver tree + discovery
  → Haystack model points + assignment graph
  → Arrow RecordBatches (Feather files on disk)
  → DataFusion SQL rules (FDD Wires + SQL builder)
  → fault state, plots, reports
  → React dashboard
```

Driver points map to **Haystack IDs** before FDD rules bind to them — rules reference semantic point names, not raw BACnet object IDs or Modbus registers.

## Where each driver appears

| Driver | Driver Tree (UI sidebar) | REST API | Dedicated container |
| --- | --- | --- | --- |
| BACnet/IP | Yes — devices and points | `/api/bacnet/*` | `openfdd-commission` (+ bridge routes) |
| Modbus/TCP | Yes — devices and registers | `/api/modbus/*` | Bridge (same binary) |
| JSON API | Yes — registered HTTP sources | `/api/json-api/*` | Bridge (same binary) |
| Haystack | Yes — gateway note + sites | `/api/haystack/*`, `/api/model/haystack` | `openfdd-haystack-gateway` |

The driver tree is persisted at `workspace/data/drivers/bacnet/driver_tree.json`. If that file only lists BACnet (for example after bench commissioning), add Modbus, JSON API, and Haystack entries back or delete the file to restore the built-in default tree.

## Related docs

- [Drivers, historian, and FDD](drivers-and-fdd.md)
- [Haystack assignment model](../ASSIGNMENT_MODEL.md)
- [AI agent route map](../ai-agent/README.md)
