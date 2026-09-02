# Data modeling — packages, utilities, export bundles

Use when ingesting campus data, wiring utility analytics, or building ML-ready exports.

## Package layout (`openfdd_package_v1`)

Authoritative ingest: [`edge/src/csv_ingest/package.rs`](../../../edge/src/csv_ingest/package.rs).

```
<building_id>/
  manifest.json              # schema_version: openfdd_package_v1
  session_config.json        # optional
  <equipment_id>/
    history_wide.csv
    history_wide.json        # equipType + points { role → column }
  utilities/                 # optional utilities_v1
    manifest.json
    electric/
      monthly_bills.csv
      utility_interval_15m.csv   # optional
      bas_submeter_interval.csv  # optional
    gas/
      monthly_bills.csv
```

**Nested wrappers:** manifests may sit several folders deep (e.g. Creekside). Ingest walks for a unique `openfdd_package_v1` manifest (depth ≤ 8).

**Wrapper utilities:** `utility_bills_monthly.csv` beside the nested package folder maps to `utilities/electric/monthly_bills.csv`.

## Equipment typing

- Stamp `equipType` / `equipment_type` in package maps — preferred over id heuristics.
- Opaque ids are valid (`AC_1` + `equipType: ahu`).
- Meters: `equipType: meter` with roles `kwh`, `electric_kw` for `SV-*` and `UTIL-*` rules.

## Utility FDD rules

| Rule | Compare |
|------|---------|
| `UTIL-MONTHLY` | BAS monthly kWh sum vs `utility_monthly.kwh` |
| `UTIL-INTERVAL` | BAS 15m vs `utility_interval` (MAE threshold) |
| `SV-*` | Sensor validation on meter roles (`kwh`, `electric_kw`) |

SQL: `sql_rules/util_monthly_fault.sql`, `util_interval_fault.sql`. Registry: `sql_rules/registry.yaml`.

## Engineering & ML export (`openfdd_engineering_bundle_v1`)

Rust-first: `POST /api/jobs/{job_id}/exports` (profiles: summary, diagnostic, forensic).

Key paths in ZIP:

- `MANIFEST.json`, `README.md`
- `catalog/equipment.json`, `catalog/feature_catalog.json`
- `labels/label_catalog.json`
- `splits/chronological_splits.json`
- `summaries/utility_monthly_electric.csv` when utilities present
- `data/package_snapshot/` (diagnostic/forensic)

Offline validator: `scripts/openfdd_bundle_validate.py validate <bundle.zip>`

Deprecated alias: `POST /api/jobs/{job_id}/wattlab/dumps`

## Pandas quick joins

```python
import pandas as pd
hist = pd.read_parquet("data/telemetry/AHU_1.parquet")  # when present in bundle
bills = pd.read_csv("summaries/utility_monthly_electric.csv")
```

## Legacy fuel campus ZIP

Read-only: `services/central/src/fuel/import.rs` — do not use for new sites; import utilities via package.
