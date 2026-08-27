# ARCHIVED — do not implement

**Status:** Historical only. Feather dual-write and `edge/src/historian/feather_store.rs` were **deleted** (Plan 4 / PR #789).

**Current contract:** durable historian = **Parquet only** under `OPENFDD_STORAGE_URL` (same volume/`s3://` across GHCR image updates). See [`AGENTS.md`](../../AGENTS.md), [`openfdd_agent_spec/HISTORIAN_PROGRAM.md`](../../openfdd_agent_spec/HISTORIAN_PROGRAM.md), and [`docs/operations/RAILWAY_DEPLOYMENT_CHECKLIST.md`](../operations/RAILWAY_DEPLOYMENT_CHECKLIST.md).

For BACnet OT product work today, use `openfdd-fieldbus` + MQTTS ingest — not this prompt.

<details>
<summary>Original vibe16 Feather-port prompt (obsolete)</summary>

The former instructions told agents to dual-write Feather shards via `feather_store::write_wide_shard`. That path no longer exists. Do not resurrect it.

</details>
