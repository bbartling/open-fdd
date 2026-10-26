# Migration matrix (current)

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

| Area | Disposition | Notes |
| --- | --- | --- |
| Product UI | React SPA (`frontend/web`) | Sole product surface |
| Product FDD | DataFusion SQL (`sql_rules/`) | No pandas in request path |
| Product analytics | `/api/analytics/*` historian DF | Client Plotly presentation |
| PyPI `open_fdd` | Keep forever | Third-party / oracle / ECM / reporting libs |
| SQL + pandas cookbooks | Keep both | Production vs oracle expressions |
| vibe19 playground | External companion | Pandas demo image |
| vibe20 playground | External companion | EnergyPlus studio |
| WattLab AFDD zip export | Offline tooling | `tools/wattlab_export`; opt-in env only |
| `edge/`, `os/` | Keep | Future concepts |
