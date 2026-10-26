# Offline engineering notebook (not in the SPA)

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

Open-FDD keeps **Python ML offline** (vibe21 / WattLab notebooks +
`scripts/vibe21_master_build.sh`). Do **not** embed an IPython kernel in the
React app.

Community-facing flow:

1. Calibrate BEST twin (WattLab / G14).
2. Farm → Parquet (Arrow) → optional pandas analysis offline.
3. sklearn family hunt → champion → `model.trees.json` / conformance + `runtime_bundle.json`.
4. Rust central serves Unity ZIP + `/api/v1/predict/demand_hourly` (Python-free images).

DataFusion reads Arrow/Parquet for FDD/QC; training stays outside GHCR.
