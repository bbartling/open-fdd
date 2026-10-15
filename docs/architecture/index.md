---
title: Architecture
layout: default
nav_order: 3
has_children: true
permalink: /architecture/
---

# Architecture

Container stack for telemetry, modeling, and HVAC FDD. Soft-OPEN ≠ FQ.

| Layer | Role |
|-------|------|
| `openfdd-fieldbus` | On-prem BACnet/Modbus → MQTTS |
| `openfdd-mqtt` | Mosquitto MQTTS |
| `openfdd-central` | **Timescale** historian + `.sql` FDD + JWT REST |
| `openfdd-web` | React SPA → `/api` |
| `openfdd-mcp` | Optional read-first stdio |

Product FDD / analytics = **Timescale SQL** ([ADR-010](adr-010-timescale-hard-cutover.md)). PyPI `open-fdd` = third-party oracle.

## Guides

| Topic | Document |
|-------|----------|
| [Services](services.html) | Images / compose |
| [Data flow](data-flow.html) | Ingest → model → FDD → UI |
| [Timescale historian](storage-and-datafusion.html) | Storage + SQL (ADR-010) |
| [Historian (historical H1–H10)](historian.html) | SUPERSEDED Parquet narrative |
| [ADR-010 cutover](adr-010-timescale-hard-cutover.html) | Timescale-only lock |
| [DataFusion-first (historical)](datafusion-first.html) | SUPERSEDED |
| [Job workspaces](job-workspaces.html) | `workspace/jobs/` |
| [Multi-client hosting](ADR_multi_client_shared_hosting.html) | Tenant sketch |
| [Data model graph](ADR_data_model_graph.html) | Haystack / RDF |

## Operator flow

1. **Map** — package roles → SQL columns  
2. **Ingest** — MQTTS or CSV → Timescale  
3. **Detect** — Lab / `POST /api/fdd/run` + `/api/analytics/*`  
4. **Act** — Reports, health, RCx; agents via JWT / MCP  

LAN / VPN first. Do not expose central on the public internet without review.
