---
name: openfdd-architecture
description: >-
  Use when enforcing Open-FDD product boundaries: Timescale and PostgreSQL SQL
  versus the pandas oracle, Normal Framework portal and CSV ingest, local
  single-host central and web, vibe19/vibe20 ownership, dual cookbooks, and the edge helper
  crate. Triggers on: architecture, ownership, pandas fallback, cookbook delete,
  Milestone A Phase 0, architecture_epoch.
---

# Open-FDD architecture

`architecture_epoch: portal-timescale-v1`.

Read [`ARCHITECTURE.md`](../../ARCHITECTURE.md) and [`ownership.yaml`](../../ownership.yaml).

## Non-negotiables

- **TIMESCALE/POSTGRESQL ONLY. ONE CANONICAL TELEMETRY WRITE PATH. NO DUAL RECORD WRITING.** Canonical text: [`DATA_CONTRACT.md` § Storage mandate](../../DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory).
  - Parquet, Apache Arrow, Arrow IPC, Feather and DataFusion are prohibited in active product storage, caching, execution and dependencies. Only `archive/` may contain them, labeled historical.
  - Derived FDD / analytics results persist in PostgreSQL or bounded memory.
  - NF REST, local NF gRPC (planned) and CSV share one validated, idempotent Timescale telemetry writer. No parallel historian, raw-data mirror, or legacy fallback. That writer records changed sample ranges and advances the site data revision in the same transaction. An identical replay does not. One FDD result is the data revision, model revision, rule parameters, pack version, window, and quality and schedule policy (`fdd_tsdb::FddResultIdentity`).
  - Haystack RDF / parsed SPARQL, durable job and coverage metadata, audit logs, model snapshots and on-demand exports stay; none may become another raw telemetry store.
  - Known gap, not permitted: the remaining `crates/fdd_store` Arrow / Parquet modules (historian sidecar, compaction, disk budget), removed in Wave P2. The analytics result cache is the PostgreSQL `analytics_result` table.
- Production FDD and analytics = Timescale / PostgreSQL (`sql/fdd/`) on central. No silent pandas fallback ([ADR-010](../../../docs/architecture/adr-010-timescale-hard-cutover.md)).
- Ingest = Normal Framework portal API and CSV. MQTT ingest is disabled by default in 4.x. MQTT, BACnet, Modbus, Haystack wire, and fieldbus are an unqualified archive. Historical, superseded by the Timescale-only mandate: MQTTS once kept a small ingest buffer keyed by the envelope site id. That buffer is not a live path and is not a second telemetry store.
- Product services = central + web, with Timescale, on the local single-host stack. Optional image: `openfdd-mcp`. Railway and any cloud web-app hosting are retired and prohibited.
- Pandas oracle = `open_fdd.rules` + `analytics` — permanent, outside the product request path.
- Both cookbooks stay. The SQL cookbook filename `datafusion-sql-cookbook.md` is an expression record, not the engine. See [`docs/COOKBOOK_OWNERSHIP.md`](../../docs/COOKBOOK_OWNERSHIP.md).
- Sole product UI = React SPA (`frontend/web` → `openfdd-web`) → central `/api` only.
- Product central image = Rust/debian only — no Python runtime.
- `edge/` is the package, semantic, and SQL helper central links. Never delete `edge/` or `os/`. The edge process is under `archive/ot-edge/`.
- Do not rename `open_fdd.rules` → `open_fdd.oracle` without a product decision.
- Keep [`../../AGENTS.md`](../../AGENTS.md) / [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) / this skill honest when product truth changes.
- Vendor dictionaries, campus names, and weather lat/lon stay in preprocess zips, never in product SQL or UI.
- Historical OT commands are `historical/non-executable`: [`docs/archive/ai-agent/historical-3.5-ot-ops.md`](../../../docs/archive/ai-agent/historical-3.5-ot-ops.md).

## Phase 0 coding (when executing)

Add CI that validates `ownership.yaml` and fails on prohibited imports, missing cookbook paths, or terminology regressions.

## Skill home

`openfdd_agent_spec/skills/` is the only authoring tree. Do not create a parallel copy under `.cursor/skills/`, `.claude/skills/`, `.agents/skills/`, or a home directory. Sync with [`scripts/openfdd_install_agent_skills.sh`](../../../scripts/openfdd_install_agent_skills.sh) (`--sync`, optional `--user`). Orientation: [`openfdd_agent_spec/AGENTS.md`](../../AGENTS.md) and the repo [`AGENTS.md`](../../../AGENTS.md).

## Related skills

- [`openfdd-sql-fdd`](../openfdd-sql-fdd/SKILL.md) — product FDD engine
- [`openfdd-react-spa`](../openfdd-react-spa/SKILL.md) — product UI
- [`openfdd-code-review-rust-react`](../openfdd-code-review-rust-react/SKILL.md) — Rust and React review standard
- [`openfdd-pypi-oracle`](../openfdd-pypi-oracle/SKILL.md) — library boundary
- [`openfdd-milestone-a-pr`](../openfdd-milestone-a-pr/SKILL.md) — PR loop
- [`openfdd-stack-ghcr`](../openfdd-stack-ghcr/SKILL.md) — image pull
