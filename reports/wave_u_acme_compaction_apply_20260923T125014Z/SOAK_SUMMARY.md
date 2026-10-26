# ACME compaction APPLY (`wave_u_acme_compaction_apply_20260923T125014Z`)

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

| Metric | Value |
|--------|-------|
| Hub | https://openfdd-web-production-af99.up.railway.app |
| Before (plan_only) | plans=40 files=54814 bytes=86694071 |
| After (plan_only) | plans=0 files=0 bytes=0 |
| APPLY ok | true |
| Partitions compacted | 40 |
| Input files collapsed | 54814 |
| Input bytes | 86694071 (~82.7 MiB) |
| Output bytes | 1651755 (~1.6 MiB) |
| OPENFDD_PARQUET_FLUSH_SECONDS | set to **300** on central (redeploy with AFDD pin) |

Hard gate for continuous AFDD: **PASS** (eligible multi-part plans = 0 after APPLY).
