# Single-system and building-folder AHU FDD/RCx Typst

**Date:** 2026-09-26
**Status:** Shipped on the anomaly-screening CLI branch
**Package:** PyPI `open-fdd` (`open_fdd.reporting.single_system_typst`, CLI `open-fdd-anomaly report`)

## Goal

Give any agent an offline recipe that turns a device folder (`history_wide.csv` + `column_map.json`) into engineer-facing Typst sources for one AHU, and the same section order for every AHU child of a building folder.

The sacred BUILDING_100 Overview-mirrored lab PDF stays on the external legacy kit (`main.typ`, `render_plots.py`, `build_typst_body.py`). This pack must not overwrite that layout or its Overview PNGs.

## Scopes

| Scope | Input | What is reported |
| --- | --- | --- |
| `single-system` | One device folder | That AHU |
| `building` | Parent of device subfolders | Each child with AHU IO. Other children are listed as skipped |

v1 fixture and sample PDF are one AHU (`tests/reporting/fixtures/ahu_typst_mini/`). A whole-building Overview narrative is still the legacy kit when the site is BUILDING_100.

## Section order

1. Data health: coverage and physical bounds from cookbook sensor limits. Not anomaly minutes.
2. Sensor-validation oracle (`SV-*`) when mapped roles exist.
3. Anomaly scoreboard. Unsupervised screens are not FDD. Fan-ON fraction is stated; FC1 and economizer rules keep their cookbook fan-ON gates.
4. FC1 duct static vs setpoint, with fan command on a separate axis.
5. Economizer rules `FC2`, `FC3`, `FC10`, `FC11`, `ECON-1`, `ECON-2`, `ECON-4`.
6. Fan-on `economizer_delta_scatter`: **x = OAT − RAT** (`delta_or_f`), **y = MAT − RAT** (`delta_mr_f`), reference lines y = OA fraction × x (0/25/50/75/100%). Points come from `build_economizer_delta_points`. Fan ON and |OAT−RAT| ≥ 10°F. Do not plot OAT−MAT vs RAT−MAT.

## Railway

When a JWT and `OPENFDD_API_BASE` are already available, mapping inventory is `GET /api/csv/import/package/mapping?building_id=BUILDING_100`. A local package zip can be sent through `scripts/agent_eplus_dump.sh`. The report command itself only reads a folder on disk. CI does not need those credentials.

## Command

```bash
pip install "open-fdd[anomaly]"
open-fdd-anomaly report ./AHU_1 --out ./ahu1_report
open-fdd-anomaly report ./BUILDING --scope building --out ./bldg_report
typst compile ./ahu1_report/report.typ ./ahu1_report/report.pdf
```
