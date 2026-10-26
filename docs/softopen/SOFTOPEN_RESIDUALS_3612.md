# Soft-OPEN residuals snapshot — 3.6.12

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

Soft-OPEN ≠ FQ.

| Area | Soft-OPEN state |
| --- | --- |
| R5 SPARQL | Algebra policy (SELECT/ASK; reject Update/SERVICE/FROM) **before** dataset materialize |
| R8d compaction/budget | Timescale tip: Parquet compaction + Parquet data-budget Soft-OPEN N/A envelopes |
| Tip prior | 3.6.11 / sha-cfc1f56 live Soft-OPEN before this PR |
| Volume Deletes | Owner UI BLOCKED |
| Grok ART | NOT_AVAILABLE — stop spam |
| WAL / restore FQ | Still open (≠ Soft-OPEN) |

Locks: Rust · Timescale only · `/tmp` worktrees · no backups · Soft-OPEN ≠ FQ.
