---
title: Architecture
layout: default
nav_order: 3
has_children: true
permalink: /architecture/
---

# Architecture

Open-FDD is a **container stack** for building telemetry, semantic modeling, and supervisory HVAC fault detection.

| Layer | Role |
|-------|------|
| **`openfdd-fieldbus`** | On-prem BACnet / Modbus / Haystack OT → MQTTS |
| **`openfdd-mqtt`** | Mosquitto MQTTS broker (hub or campus) |
| **`openfdd-central`** | Parquet historian, DataFusion SQL FDD + analytics, JWT REST |
| **`openfdd-web`** | React SPA (Overview, Lab, RCx, Reports) — same-origin `/api` |
| **`openfdd-mcp`** (optional) | Read-first stdio tools for external agents |

Product FDD and Overview analytics are **DataFusion SQL only**. PyPI `open-fdd` (pandas / ECM) is third-party oracle tooling — not the request path.

## Guides

| Topic | Document |
|-------|----------|
| [Services](services.html) | Images and compose roles |
| [Data flow](data-flow.html) | Drivers → model → historian → FDD → UI |
| [Storage & DataFusion](storage-and-datafusion.html) | Parquet historian and SQL rules |
| [Historian architecture](historian.html) | Hive layout, compaction, scale honesty |
| [DataFusion-first](datafusion-first.html) | Computation boundary |
| [Job workspaces](job-workspaces.html) | Durable Jobs under `workspace/jobs/` |
| [Analytics boundary](analytics-boundary.html) | Typed DF analytics vs React |
| [VAV health matrix](adr-vav-health.html) | Cohort broken / comfort / rogue scores |
| [Multi-client hosting](ADR_multi_client_shared_hosting.html) | Tenant isolation sketch |
| [Data model graph](ADR_data_model_graph.html) | Haystack / RDF contract |

## Operator mental model

1. **Map once** — package zip stamps Haystack roles → SQL columns (`sat`, `oa_t`, `fan_status`, …).
2. **Ingest** — live MQTTS or CSV/package import into Parquet under `OPENFDD_STORAGE_URL`.
3. **Detect** — Lab / `POST /api/fdd/run` evaluates `sql_rules/registry.yaml`; Overview tables call `/api/analytics/*`.
4. **Act** — Reports, health matrices, RCx Plots; agents use JWT REST or MCP.

LAN / VPN / OT-oriented. Do not expose central on the public internet without an independent security review.
