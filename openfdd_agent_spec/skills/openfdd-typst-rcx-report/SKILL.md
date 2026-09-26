---
name: openfdd-typst-rcx-report
description: >-
  Build engineer-facing Typst lab PDFs from live DataFusion Overview / RCx /
  Inspect APIs. Covers VAV AHU (BUILDING_100), heat-pump + metering (LAKESIDE_ES /
  Creekside), and MQTTS zone monitoring (bldg2). CRITICAL: preserve Overview-
  mirrored charts; never strip reports to thin package layouts. Triggers on:
  typst rcx, rcx lab report, heat pump report, lakeside, creekside, mqtts zone
  PDF, building100_rcx_report, elec_power metering PDF, box plot, seasonal heat cool,
  open-fdd-anomaly report, single-system AHU Typst, AHU_1 FDD RCx PDF.
---

# Open-FDD Typst lab reports (multi-profile)

**Not** the product PDF path (`rust-text-pdf`). Agent lab screening pack:
DataFusion → Plotly (UI palette) → Typst → PDF + CSVs for Excel.

Reference kit: `/home/ben/building100_rcx_report/` when that directory is present.
The single-AHU command does not read it. A missing kit is not a blocker for
`open-fdd-anomaly report`.

**PyPI staging (not in open-fdd master yet):** package `open-fdd-lab-typst`
(`openfdd_lab_typst`, CLI `open-fdd-lab-typst`). Future monorepo path
`open_fdd.lab_typst` — see kit `FUTURE_OPENFDD_MERGE.md`.

**Chart parity (W-CHART):** React Plotly (`frontend/web/src/api/plotlyTheme.ts`
`RAINBOW_PALETTE`) is the visual SoT. Prefer `open_fdd.analytics.charts` helpers
(and `overview_export`) over ad-hoc matplotlib colors. Permanent lock:
`tests/analytics/test_chart_palette_parity.py` +
`tests/reporting/test_report_chart_palette.py` +
`frontend/web/src/api/charts.contract.json` (Inspect title/domains, PNG stem
vocabulary). Plan: `.cursor/plans/agent_report_chart_parity.plan.md`. Day-zoom
PNGs use the same rainbow list as of `open-fdd>=4.4.5`. Findings/report chrome
bars cycle rainbow like React `rankingBars` as of `open-fdd>=4.4.6`. Inspect twin
matches React stacked domains as of `open-fdd>=4.4.6`. React Overview-RCx PNG
stems are bare contract ids (`mech_cooling_oat_bins`, …); Typst/report assets keep
Soft-OPEN `overview_*` aliases from `png_stem_vocabulary.pypi_overview_export`.

---

## NEVER vibe-code these reports (hard law)

These rules exist because agents previously **destroyed** good Overview-mirrored
PDFs by regenerating thin package layouts. Violating them is a regression.

### Sacred deliverables (kit root)

| File | Pipeline | Sacred? |
|------|----------|---------|
| `BUILDING_100_RCx_Lab_Report.pdf` | **Legacy only** | **YES — never replace with package strip-down** |
| `LAKESIDE_ES_Creekside_HeatPump_RCx_Lab_Report.pdf` | Package `heat_pump` | Keep runtime/comfort/OAT/meter/geo/HP detail |
| `LAKESIDE_ES_Creekside_Seasonal_HeatCool_RCx.pdf` | `seasonal_hp` | Separate from HeatPump report — do not overwrite HeatPump PDF |
| `bldg2_MQTTS_Zone_Lab_Report.pdf` | Package `mqtts_zone` | Keep zone T/RH + weather |

### BUILDING_100 — Overview mirror forever

1. **Always** use legacy kit scripts — never `openfdd_lab_typst.render` / `typst_build` for this site.
2. CLI already forces legacy when `--building BUILDING_100`.
3. Sacred Typst entry: kit-root **`main.typ`** (charts-before-tables, plot-type layout).
   - Includes: zone comfort, weekly runtimes (air/boiler/chiller), **mech cooling OAT bins**,
     BAS/web OAT, plant scatters, FDD fault hours + caption, econ Δ/MAT/temps (dual-axis damper %),
     FC1 / SATDEV / FC13 / ECON-1 / ECON-4 overlays with `confirmed_fault`, then Overview tables.
4. **Additive only:** box plots (`bx_sat_leave`, `bx_duct_static`, `bx_fan_speed`) — same unit per chart.
5. **Do not** overwrite `main.typ` with package `write_main_typ`.
6. **Do not** replace Overview PNGs (`02_site_runtime_*`, `03_site_mech_cooling_bins`, `11_econ_temps_*`,
   `12_fdd_*` …) with crappy multi-role line dumps (`50_AHU_*.png`).
7. Regen command:

```bash
cd /home/ben/building100_rcx_report
# optional: skip fetch if data fresh
.venv/bin/python render_plots.py
.venv/bin/python build_typst_body.py
typst compile main.typ BUILDING_100_RCx_Lab_Report.pdf
# or: open-fdd-lab-typst --building BUILDING_100 --skip-fetch
```

### Offline single-system and building-folder pack (in this repo)

This path is **additive**. It does not render, replace, or overwrite the sacred
BUILDING_100 Overview PDF, `main.typ`, or Overview PNG stems.

| Scope | Input | Command |
| --- | --- | --- |
| `single-system` | One device folder (`history_wide.csv` + `column_map.json`), v1 focus `AHU_1` | `open-fdd-anomaly report ./AHU_1 --out ./ahu1_report --month 2026-06` |
| `building` | Parent folder of device subfolders. AHU IO is reported; VAV/other children are skipped in the summary | `open-fdd-anomaly report ./BUILDING --scope building --month 2026-06 --out ./bldg_report` |

April device folder (local prep, not fetched in CI): 8640 rows at 5 minutes,
`2026-04-01` through `2026-04-30`, plus a 15-minute Open-Meteo sidecar whose
dry-bulb column is `web_oa_t` or `web-outside-air-temp`. Recommended RCx week
is `2026-04-06` through `2026-04-12` (about 54% fan-ON):

```bash
open-fdd-anomaly report ./AHU_1 --out ./april_report --month 2026-04 \
  --web-oat ./open_meteo_april.csv \
  --week 2026-04-06 \
  --compile
```

The in-repo fixture stays `2026-06` (`tests/reporting/fixtures/ahu_typst_mini/`).
CI must not download that April folder or call Open-Meteo.

Module: `open_fdd/reporting/single_system_typst.py`. Requires `open-fdd[anomaly]`
plus Plotly (`open-fdd[reporting]` is what CI installs). The PDF is produced by
the same command: add `--compile`. That flag runs `typst compile` when the
`typst` binary is on `PATH` and writes `report.pdf` next to `report.typ`.
A follow-up hand compile is not the shipped path.

**Month filter (required for the analysis window).** `--month YYYY-MM` keeps every
rule and plot inside that UTC calendar month. Omit it and the command uses the
month with the most samples. The in-repo fixture month is **`2026-06`**
(`tests/reporting/fixtures/ahu_typst_mini/`). An empty month is an error.

**Web outdoor-air temperature.** Rules that need `web-outside-air-temp` (including
`OAT-METEO` and economizer rules with a web-OAT role) run only after a join:

1. Mapped column `web-outside-air-temp` already on `history_wide.csv`, or
2. `--web-oat weather.csv` with `timestamp_utc` and a dry-bulb column
   (`web-outside-air-temp`, `dry_bulb_f`, or `web_oa_t`), or
3. `--web-oat fetch --lat <deg> --lon <deg>` which calls
   `open_fdd.analytics.open_meteo.fetch_open_meteo`.

`load_web_oat_csv` renames `web_oa_t` to `web-outside-air-temp`. `align_to_index`
reindexes a 15-minute file onto the BAS clock (time interpolation). Join goes
through `merge_weather` / `weather_resolver`, then `prefer_web_oat` so web
outdoor air is the effective series. BAS `outside-air-temp` is not overwritten.
The RCx figure is `bas_vs_web_oat_overlay`. CI must not call the network; pass
a CSV or a mapped column.

**Do not vibe-code this PDF.** Call the PyPI helpers. No matplotlib axis invention.
Never put anomaly science in the PDF: no histograms, no scoreboard, no day zooms,
no Isolation Forest / STL / MAD / Z-score chronology. Anomaly screening is a
pass/fail bullet list in everyday words.

| Figure | Helper |
| --- | --- |
| Profile selection | `open_fdd.reporting.report_template`. `vav_ahu` is implemented. `cv_ahu`, `single_zone`, `chiller`, `boiler`, `heat_pump`, `vav_box`, `fan_coil`, `geothermal_field`, and `data_hall` are registered stubs. A figure is drawn only when its roles are mapped. |
| Econ temps + damper | `economizer_temps_overlay` (temperature axis + damper % axis, fan running). Do **not** also emit `ahu_dats`, `ahu_mats`, `ahu_rats`, `ahu_dampers`, `ahu_cooling_valves`, or `fan_speeds`. |
| Supply air vs web OAT | `collect_oat_scatter` + `oat_scatter` (`ahu_sat_reset_scatter`), fan running, web outdoor air on x. Skip when web OAT is absent. |
| Duct static box | `collect_role_series(..., filter_fan_on=True)` + `multi_equipment_box` (`duct_static_box`). |
| Duct static + setpoint | `multi_equipment_timeseries` when duct static is mapped. |
| BAS vs web OAT | `bas_vs_web_oat_overlay` when web OAT was joined. Not the histogram. |
| Fault overlay | `charts.rule_result_chart` **only** for non-SV rules when `status == FAULT` and confirmed fault hours in the month are > 0. Under each figure: a troubleshoot line from `rule_troubleshoot` (equation + summary) and a plain “in the data” line for that fault window. |
| Economizer scatter | `build_economizer_delta_points` + `economizer_delta_scatter(..., viewport="bottom_left")`. `economizer_delta_frame` is the same function (older local trees). Keep the `build_economizer_delta_points` name. |
| Agent notes | Optional prose in `ai_comments.json` (slots: sensor_checks, anomaly_screening, executive_summary, rcx_week, confirmed_faults, economizer). Empty slots are omitted. The PDF has no re-run command. |

History sources (`HISTORY_SOURCES`): `device_folder` (implemented), `openfdd_api` (any Open-FDD central; pass a reader, no network inside the class), `vendor_api` (registered stub). `--week YYYY-MM-DD` pins seven days (April example `2026-04-06`). Omit it and the window is the 7 days in the month with the most fan-ON samples.

Ordered sections for facility / RCx readers (keep this order):

1. **Sensor checks first.** SV rules for the mapped sensors. List only checks with findings, in plain language (stuck flat, reading out of physical range, sudden jump, stopped updating). If every check is clean, one “Passed” bullet. Do not invent findings.
2. **Anomaly screening second, high-level only.** One bullet per varying trend: “looks normal”, “needs a look”, or “skipped — not enough fan-on data”. If something needs a look, add one everyday sentence about the trace (for example a sudden dropout). Do not treat that sentence as an equipment fault. No method names.
3. **Executive summary** that opens with the sensor-check outcome and the plain anomaly outcome, then confirmed operating findings rounded to 1 decimal.
4. RCx week figures selected from mapped roles: economizer rainbow (OAT/RAT/MAT/SAT plus damper percent), fan-on supply air vs web outdoor air, fan-on duct-static box, duct static with setpoint, and BAS/web overlay when web OAT exists. Do not add the duplicate timeseries presets listed above.
5. Confirmed operating-fault figures only (not the SV bullets). Under each figure: how to troubleshoot (rule equation) and what the fault window shows, in plain language.
6. Economizer delta scatter. **x = OAT − RAT** (`delta_or_f`), **y = MAT − RAT** (`delta_mr_f`). Reference lines y = OA fraction × x for 0/25/50/75/100% OA. Fan ON and |OAT−RAT| ≥ 10°F. **Viewport is the bottom-left mixing quadrant only** (both deltas ≤ 0, so OAT ≤ RAT and MAT ≤ RAT). **Do not plot OAT−MAT vs RAT−MAT.**

Haystack exports store devices under `equip` (object). Flat sidecars use string `equip` plus top-level `points`. Both must resolve or the AHU is skipped.

### Railway / API for BUILDING_100

- Full-building Overview PDF: keep the legacy kit (`fetch_railway.py` → `render_plots.py` → `build_typst_body.py` → `main.typ`). Do not point that site at `build_single_system_report`.
- Single-AHU pack: only after a device folder is already on disk. CI uses `tests/reporting/fixtures/ahu_typst_mini/` (sample PDF `tests/reporting/fixtures/ahu_typst_mini_report.pdf`). Do not commit a multi-megabyte BUILDING_100 CSV.
- When `OPENFDD_API_BASE` and a JWT already exist, inventory is `GET /api/csv/import/package/mapping?building_id=BUILDING_100`. A local package zip can go through `scripts/agent_eplus_dump.sh` (engineering bundle). Neither call is required for the unit tests, and secrets stay out of CI.

### Additive changes only

When the user asks for “a few box plots / one scatter / rounding”:

| Do | Do not |
|----|--------|
| Append figures + Typst sections | Rewrite `main.typ` layout |
| Keep Overview plot styles (`overview_layout`, dual y-axis for mixed units) | Mix °F + % + in.w.c. on one axis |
| Round display values to **1 decimal** (`fmt_sensor` / `fmt_h`) | Dump raw floats (`668.166666…`) |
| Season PDF = own file | Overwrite HeatPump PDF with seasonal |
| Fan-filter leave SAT / duct static when fan ON | Invent occ_mode when only `fan_status` exists |

### Line plots with mixed units

Temps (°F) and damper/fan (%) **must** use dual y-axis (`yaxis` + `yaxis2`) — see
`render_plots.py` economizer temps overlay. Never plot damper % on the temperature axis.

---

## Profiles

| Profile | Sites | Pipeline |
|---------|-------|----------|
| `vav_ahu` / legacy | BUILDING_100 | `fetch_railway.py` → `render_plots.py` → `build_typst_body.py` → `main.typ` |
| `single_system` / `building` | device folder or building folder of devices | `open-fdd-anomaly report --compile` → `report.pdf` when `typst` is on `PATH` (does not replace the row above) |
| `heat_pump` | LAKESIDE_ES | `openfdd_lab_typst` fetch/render/typst → copy to Creekside HeatPump PDF |
| `mqtts_zone` | bldg2 | package path → copy to `bldg2_MQTTS_Zone_Lab_Report.pdf` |
| seasonal | LAKESIDE_ES | `python -m openfdd_lab_typst.seasonal_hp` → **Seasonal** PDF only |

## Hard rules (data / plots)

1. **Data model driven** — mapped cookbook roles only for inspect columns.
2. **Colors** — `RAINBOW_PALETTE` (`frontend/web/src/api/plotlyTheme.ts`).
3. **Line gaps (adaptive)** — null **Y only**. Gap = `max(3600, 4 × median_Δt)`.
4. **Full span via Inspect** — `POST /api/analytics/inspect` max_points 8000.
5. **Metering** — if `elec_power` mapped, chart kW + monthly + (optional) kW vs OAT weekday/weekend.
6. **FDD overlays** — only when results exist; do not invent faults.
7. **Round** all sensor/hour table cells and insight prose to nearest tenth.
8. **Product boundary** — do not replace `rust-text-pdf`.

## Kit layout

```text
/home/ben/building100_rcx_report/
  main.typ                 # BUILDING_100 sacred layout
  render_plots.py          # Overview-parity Plotly
  build_typst_body.py      # snapshot + insights + tables
  openfdd_lab_typst/       # package (HP / MQTTS / seasonal)
  sites/LAKESIDE_ES/       # HP + seasonal working copies
  sites/bldg2/
  AGENTS.md                # short agent gate (read first)
```

## Related

- Kit `AGENTS.md` · `README.md` · `FUTURE_OPENFDD_MERGE.md`
- Skills: `openfdd-react-spa` · `openfdd-package-mapping` · `openfdd-railway-cli`
- Wave K plan + BUG_REPORT plot-span rows
