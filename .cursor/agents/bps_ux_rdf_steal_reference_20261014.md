# Public-safe reference — BPS UX / RDF steal patterns (2026-10-14)

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

**Neutral notes only.** Private Azure DevOps / Blackstone product names, client overlays, and ADO remotes are out of scope here. Use this as a pattern checklist when aligning **public open-fdd (Rust)** with the private Python Timescale app on Windows.

Source of patterns (private plan, not copied verbatim): Haystack RDF model CRUD + TTL download, Model UI polish, SPARQL marker tree, confirmed_fault Plotly lane, metric-default units, zone comfort band.

## Product relationship (OSS)

| Product | Role |
| --- | --- |
| **open-fdd** (this repo) | Public OSS — **Rust central** + React SPA + Timescale SQL FDD |
| Private Python FastAPI app | Separate deployment — steals UX/RDF/Plotly/SQL-contract patterns from open-fdd; does **not** own OSS equations |

**Stay Rust:** do **not** port open-fdd central/API/FDD back to FastAPI. Shared truth = versioned SQL/schema/analytics pack (hash-pinned). Steal UI/RDF both ways; never fork fault equations.

## Patterns worth stealing into open-fdd Soft-OPEN

1. **Model CRUD → sync TTL → SPARQL verify** (document CRUD, not SPARQL UPDATE as editor).
2. **Download `.ttl` / JSON** from Model UI; import with dry-run diff.
3. **confirmed_fault** Plotly swim lane when fault hours / FAULT (no empty lane greenwash).
4. **Overview marker-scoped rules** via SPARQL `ph:hasTag` (SV under sensors, PID-HUNT under outputs).
5. **Zone comfort band** + runtime-in-band SQL params (imperial/metric at UI edge).
6. **Agent-context** export for model mutations (same REST as humans; JWT scoped).

## BPS global AFDD / UI gate (match in OSS)

Inspected on Windows RO mount (mechanism, not private code):

- **Scheduler-independent one-shot jobs** (OS timer/cron starts; job owns watermarks/leases).
- Daily batch: collect → Timescale upsert → SQL FDD for due windows (not full DB every tick).
- **Write-once run-all:** after cohort results exist, batch `run_all` returns cached rows (`skipped_recompute`) unless `force_new_data` (fresh samples) or **single** `rule_id` update.
- Schema shape: `site`, `point_map`, `sample` hypertable, `fdd_run`, `batch_job` — align via shared contract release, not by copying private paths.

## FORBIDDEN when using this reference

- Dual-write / Parquet co-canonical / “Parquet if Timescale miss”
- Putting Python on open-fdd central request path for FDD equations
- Copying private branding, client data, or ADO paths into public source
- Claiming FQ from Soft-OPEN smoke

## Linked open-fdd train

Continue only: [`.cursor/plans/post_wave_x_363_softopen_residuals_20261014.plan.md`](../plans/post_wave_x_363_softopen_residuals_20261014.plan.md).
