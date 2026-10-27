# ARCHIVED — do not implement

> **Historical (Railway retired 2026-10-26).** Railway and cloud web-app hosting are retired; Railway references below are `historical/non-executable`. Hosting is the local single-host stack: [LOCAL_HOSTING.md](../operations/LOCAL_HOSTING.md).

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

**Status:** Historical only. Feather dual-write and `edge/src/historian/feather_store.rs` were **deleted** (Plan 4 / PR #789).

**Current contract:** durable historian = **Parquet only** under `OPENFDD_STORAGE_URL` (same volume/`s3://` across GHCR image updates). See [`AGENTS.md`](../../AGENTS.md), [`openfdd_agent_spec/HISTORIAN_PROGRAM.md`](../../openfdd_agent_spec/HISTORIAN_PROGRAM.md), and `docs/operations/RAILWAY_DEPLOYMENT_CHECKLIST.md` (removed, historical).

For BACnet OT product work today, use `openfdd-fieldbus` + MQTTS ingest — not this prompt.

<details>
<summary>Original vibe16 Feather-port prompt (obsolete)</summary>

The former instructions told agents to dual-write Feather shards via `feather_store::write_wide_shard`. That path no longer exists. Do not resurrect it.

</details>
