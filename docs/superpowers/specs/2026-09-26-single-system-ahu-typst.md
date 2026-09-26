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

`--month YYYY-MM` filters every rule and plot (fixture example `2026-06`). Web OAT joins from a mapped `web-outside-air-temp` column, `--web-oat weather.csv`, or `--web-oat fetch --lat --lon`.

1. Executive summary: data-bound issues and confirmed fault hours, 1 decimal. Anomaly minutes are one caveat sentence, not a gallery.
2. One fan-on week of AHU RCx timeseries from `multi_equipment_timeseries` / `economizer_temps_overlay` / `bas_vs_web_oat_overlay`. No histograms.
3. `rule_result_chart` only for rules with confirmed fault hours in the month, with `rule_meta` bullets.
4. `economizer_delta_scatter` viewport `bottom_left`: **x = OAT − RAT** (`delta_or_f`), **y = MAT − RAT** (`delta_mr_f`). Do not plot OAT−MAT vs RAT−MAT.

## Railway

When a JWT and `OPENFDD_API_BASE` are already available, mapping inventory is `GET /api/csv/import/package/mapping?building_id=BUILDING_100`. A local package zip can be sent through `scripts/agent_eplus_dump.sh`. The report command itself only reads a folder on disk. CI does not need those credentials.

## Command

```bash
pip install "open-fdd[anomaly]"
open-fdd-anomaly report ./AHU_1 --out ./ahu1_report --month 2026-06
open-fdd-anomaly report ./AHU_1 --out ./ahu1_report --month 2026-06 --web-oat ./weather.csv
open-fdd-anomaly report ./AHU_1 --out ./ahu1_report --month 2026-06 --web-oat fetch --lat 43.07 --lon -89.40
open-fdd-anomaly report ./BUILDING --scope building --month 2026-06 --out ./bldg_report
typst compile ./ahu1_report/report.typ ./ahu1_report/report.pdf
```
