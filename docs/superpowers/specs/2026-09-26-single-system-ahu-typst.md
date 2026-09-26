# Single-system and building-folder AHU FDD/RCx Typst

**Date:** 2026-09-26
**Status:** Shipped on the anomaly-screening CLI branch
**Package:** PyPI `open-fdd`. The only shipped PDF command is `open-fdd-anomaly report ... --compile`.

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

`--month YYYY-MM` filters every rule and plot (fixture example `2026-06`). `--week YYYY-MM-DD` pins the RCx window to seven UTC days from that date. Web OAT joins from a mapped `web-outside-air-temp` column, `--web-oat weather.csv` (`web_oa_t` or `web-outside-air-temp`; 15-minute rows reindex onto the BAS clock via `align_to_index`, then `prefer_web_oat`), or `--web-oat fetch --lat --lon`. The RCx overlay is `bas_vs_web_oat_overlay`.

April device-folder example (documentation only; CI uses the June fixture and must not download the folder or call the network): 8640 rows at 5 minutes, `2026-04-01` through `2026-04-30`. Recommended RCx week `2026-04-06` through `2026-04-12`. The single-AHU path does not read `/home/ben/building100_rcx_report`.

`economizer_delta_frame` is an alias of `build_economizer_delta_points`. Axes stay x = OAT − RAT, y = MAT − RAT, bottom-left quadrant only.

1. Sensor checks: failed SV rules in everyday words, or one Passed bullet.
2. Anomaly screening: “looks normal” / “needs a look” / “skipped — not enough fan-on data”. No method names or science plots.
3. Executive summary opening with those two outcomes, then confirmed operating hours at 1 decimal.
4. One week of role-selected RCx figures for `vav_ahu` and `cv_ahu`: economizer temperature rainbow with damper percent, BAS vs web outdoor air when web OAT is joined, fan-on supply air vs web outdoor air, and a fan-on duct-static box. Do not also draw `ahu_dats`, `ahu_mats`, `ahu_rats`, `ahu_dampers`, `ahu_cooling_valves`, `fan_speeds`, or the duct-static timeseries. No histograms. No re-run footer.
5. `rule_result_chart` only for non-SV rules with confirmed fault hours. Under each figure: a troubleshoot line from the rule equation and a plain description of the fault window.
6. `economizer_delta_scatter` viewport `bottom_left`: **x = OAT − RAT** (`delta_or_f`), **y = MAT − RAT** (`delta_mr_f`). Do not plot OAT−MAT vs RAT−MAT. The caption under the figure (`econ_scatter_caption`) tells an engineer how to read damper color against the 0/25/50/75/100% outdoor-air lines, that damper position is not fresh-air fraction, what an off-line cloud means (mixing, sensor error, too much or too little outdoor air), and that mild weather where MAT ≈ RAT ≈ OAT shrinks the deltas. Sensor, anomaly, and executive prose come from `narrative_polish` (paragraphs, not a raw fail list). Fan-on lines break at fan-off gaps. FC1 plots duct static, fan percent, and the fault line. `unit_system: metric` labels axes °C and Pa.

The template (`open_fdd.reporting.report_template`) is not tied to a deploy host. Sources: device folder, any Open-FDD central (reader-supplied), future vendor API. `unitVentilator` / `uv` resolve to `cv_ahu` and use that same figure set. Stub profiles: `single_zone`, `chiller`, `boiler`, `heat_pump`, `vav_box`, `fan_coil`, `geothermal_field`, `data_hall`. Agents insert prose through `ai_comments.json`.

## Railway

When a JWT and `OPENFDD_API_BASE` are already available, mapping inventory is `GET /api/csv/import/package/mapping?building_id=BUILDING_100`. A local package zip can be sent through `scripts/agent_eplus_dump.sh`. The report command itself only reads a folder on disk. CI does not need those credentials.

## Command

The PDF comes only from this CLI. `build_april_report.py` and other out-of-tree runners are not in the package.

```bash
pip install "open-fdd[anomaly]"
open-fdd-anomaly report ./AHU_1 --out ./ahu1_report --month 2026-06 --compile
open-fdd-anomaly report ./AHU_1 --out ./ahu1_report --month 2026-06 --web-oat ./weather.csv --compile
open-fdd-anomaly report ./AHU_1 --out ./ahu1_report --month 2026-06 --web-oat fetch --lat 43.07 --lon -89.40 --compile
open-fdd-anomaly report ./AHU_1 --out ./april_report --month 2026-04 \
  --web-oat ./open_meteo_april.csv --week 2026-04-06 --compile
open-fdd-anomaly report ./BUILDING --scope building --month 2026-06 --out ./bldg_report --compile
# --compile writes report.pdf when typst is on PATH. Do not compile report.typ by hand.
```
