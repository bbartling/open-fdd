# Offline engineering notebook (not in the SPA)

Open-FDD keeps **Python ML offline** (vibe21 / WattLab notebooks +
`scripts/vibe21_master_build.sh`). Do **not** embed an IPython kernel in the
React app.

Community-facing flow:

1. Calibrate BEST twin (WattLab / G14).
2. Farm → Parquet (Arrow) → optional pandas analysis offline.
3. sklearn family hunt → champion → `model.trees.json` / conformance + `runtime_bundle.json`.
4. Rust central serves Unity ZIP + `/api/v1/predict/demand_hourly` (Python-free images).

DataFusion reads Arrow/Parquet for FDD/QC; training stays outside GHCR.
