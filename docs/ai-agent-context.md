---
title: AI agent context
parent: AI agents
nav_order: 1
---

# AI agent context

Canonical map for humans and MCP/RAG agents operating Open-FDD on the OT edge. **No secrets** in docs, exports, reports, or chat context.

## 1. Open-FDD in one paragraph

Open-FDD is an **edge FDD platform**: BACnet / Niagara / JSON API drivers ingest telemetry into a **BRICK-style JSON model** and **Feather/Arrow historian**; **PyArrow** (primary) and optional **DataFusion SQL** rules produce boolean fault masks with a shared **confirmation window**; the **Operator Bridge** dashboard and **MCP sidecar** expose commissioning, Rule Lab, batch FDD, and doc search. Deploy via **GHCR Docker** (`openfdd-bridge`, `openfdd-commission`, `openfdd-mcp-rag`) on a trusted LAN — not the public internet.

## 2. Deployment mental model

| Piece | Role |
|-------|------|
| **GHCR stack** | `openfdd-bridge` (API + UI), `openfdd-commission` (BACnet poll), `openfdd-mcp-rag` (doc RAG) |
| **Host Caddy** | `:80` / `:443` front door to bridge |
| **`workspace/`** | Model, rules, feather store, auth env — persist across image upgrades |
| **Auth** | `workspace/auth.env.local` (gitignored); JWT via `POST /api/auth/login` |
| **Update** | [Updating the stack]({{ "/quick-start/updating/" | relative_url }}) · [Live site update]({{ "/ops/live_site_update/" | relative_url }}) · pin `OPENFDD_IMAGE_TAG` |

Rebuild MCP index after doc changes: `./scripts/build_mcp_rag_index.sh`.

## 3. Source / driver modes

| Mode | Feather `source` | When |
|------|------------------|------|
| **BACnet direct** | `bacnet` | Production OT — commission container polls `:47808` |
| **Niagara baskStream** | `niagara_baskstream` | Bench / sites with Niagara HTTP API |
| **JSON API** | `json_api` | Weather, REST sensors, OpenWeather demo |
| **Platform API profile** | scaffold | Future portfolio central — not production duplicate poll |

Do **not** run legacy BACnet poll alongside Docker **commission** on the same device (double poll). Validation smokes may intentionally dual-source **Bench 5007** only.

## 4. Data model contract

Commissioning bundle: `GET /api/model/commissioning-export` → `POST /api/model/commissioning-import` (dry-run in UI first).

| Field | Rule |
|-------|------|
| `sites[]`, `equipment[]`, `points[]`, `fdd_rules[]` | Required structure |
| Point `id` | **Preserve** on import — never renumber |
| `fdd_input` | Rule column role (`oa-t`, `zn-t`, `sat`, …) |
| `metadata.series_id` | Historian series key |
| `metadata.external_ref` | Stable feather/BACnet reference |
| `fdd_rule_ids` | Must reference existing `fdd_rules[].id` — **never invent rule IDs** on import |
| Column map | `open_fdd.arrow_runtime.build_column_map_from_model_points(model, site_id)` |

Live HVAC reference model: **ACME** (`site_id: acme`) — fixture at `workspace/data/fixtures/acme_data_model.json`. Bench dual-source model: site `demo` / device 5007 — not ACME.

## 5. Rule execution contract

| Backend | Use when |
|---------|----------|
| **PyArrow** (`apply_faults_arrow`) | Full HVAC logic, rolling windows, ML prep, cookbook helpers |
| **DataFusion SQL** (`backend: datafusion_sql`) | Simple threshold / CASE / SQL-readable rules; optional `pip install open-fdd[datafusion]` |

Both normalize to **Arrow boolean mask** / `ArrowRuleResult`. SQL runs **server-side only** against registered `telemetry`; unsafe SQL is rejected. No browser-side SQL. No pandas row-loop runtime on edge.

## 6. Fault confirmation window

- **Raw fault** — rule mask true on one row.
- **Confirmed fault** — `min_true_rows` consecutive trues and/or `min_elapsed_minutes` elapsed.
- Example: **10 rows** at **1-minute** polling ≈ **10 minutes** confirmed.

See [Fault confirmation]({{ "/rule-cookbook/fault-confirmation/" | relative_url }}).

## 7. Validation modes

| Mode | Purpose |
|------|---------|
| **Bench 5007** | Dual-source BACnet vs Niagara backend equivalence — [long FDD smoke]({{ "/operations/bench-5007-long-fdd-smoke/" | relative_url }}) |
| **ACME live** | Real BACnet HVAC, VAV/AHU rules, RCx — [ACME live validation]({{ "/operations/acme-live-validation/" | relative_url }}) |
| **Synthetic CI** | `python scripts/smoke_bench_5007_long_fdd.py --synthetic --dry-run` |
| **Model fixture** | `python scripts/validate_acme_model_context.py` |

## 8. Security rules

- **No secrets** in docs, logs, exports, MCP bundle, or validation reports.
- Bridge binds **127.0.0.1** by default; LAN exposure requires explicit operator choice.
- **BACnet writes** disabled/guarded — see [BACnet write safety]({{ "/security/bacnet-writes/" | relative_url }}).
- Niagara / JSON API service accounts: dedicated, read-only where possible.
- Full tracebacks only when `OFDD_DEBUG_TRACEBACKS=1`.

## 9. Where to look

| Topic | Doc |
|-------|-----|
| Start | [Quick Start]({{ "/quick-start/" | relative_url }}) · [Health check]({{ "/quick-start/health-check/" | relative_url }}) |
| Drivers | [Driver framework]({{ "/drivers/" | relative_url }}) · [BACnet]({{ "/bacnet/" | relative_url }}) |
| Rules | [Rule Cookbook]({{ "/rule-cookbook/" | relative_url }}) · [DataFusion SQL]({{ "/datafusion-sql-rules/" | relative_url }}) |
| API | [API routes]({{ "/appendix/bridge_api/" | relative_url }}) |
| Operations | [Operations]({{ "/ops/" | relative_url }}) · [Deployment validation]({{ "/ops/deployment-validation/" | relative_url }}) |
| Architecture | [ADR: Rust-ready Arrow contract]({{ "/adr/adr-rust-ready-arrow-fdd-contract/" | relative_url }}) |
| MCP | [MCP server]({{ "/ai/mcp-server/" | relative_url }}) |
| Contributor policy | `AGENTS.md` (repo root) |
