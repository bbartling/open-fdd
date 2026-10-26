# Product runtime

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

Open-FDD product runtime is **Rust central + DataFusion SQL** (no Python in the
request path). Python/`open_fdd` PyPI is third-party tooling and cookbooks only.
See [`openfdd_agent_spec/ARCHITECTURE.md`](../../../openfdd_agent_spec/ARCHITECTURE.md).
