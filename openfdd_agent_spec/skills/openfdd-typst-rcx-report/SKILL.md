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

Reference kit: `/home/ben/building100_rcx_report/`.

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

Module: `open_fdd/reporting/single_system_typst.py`. Requires `open-fdd[anomaly]`
plus Plotly (`open-fdd[reporting]` is what CI installs). Optional PDF:
`typst compile report.typ report.pdf` or `--compile` when `typst` is on `PATH`.

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

Join goes through `merge_weather` / `weather_resolver` and does not overwrite BAS
`outside-air-temp`. CI must not call the network; pass a CSV or a mapped column.

**Do not vibe-code this PDF.** Call the PyPI helpers. No matplotlib axis invention.
Never put anomaly science in the PDF: no histograms, no scoreboard, no day zooms,
no Isolation Forest / STL / MAD / Z-score chronology. Anomaly screening is a
pass/fail bullet list in everyday words.

| Figure | Helper |
| --- | --- |
| AHU RCx week lines | `rcx_plots.PRESETS` where `family == "AHU / air"` and `chart == "timeseries"`, drawn with `charts.multi_equipment_timeseries` (`RAINBOW_PALETTE`). One 7-day window inside the month with the most fan-ON samples. Skip the preset when the role is unmapped. |
| Econ temps + damper | `economizer_temps_overlay` (temperature axis + damper % axis) |
| BAS vs web OAT | `bas_vs_web_oat_overlay` when web OAT was joined. Not the histogram. |
| Fault overlay | `charts.rule_result_chart` **only** for non-SV rules when `status == FAULT` and confirmed fault hours in the month are > 0. Skip the rule entirely otherwise. Sensor checks stay bullets, not these figures. |
| Economizer scatter | `build_economizer_delta_points` + `economizer_delta_scatter(..., viewport="bottom_left")` |

Ordered sections for facility / RCx readers (keep this order):

1. **Sensor checks first.** SV rules for the mapped sensors. List only checks with findings, in plain language (stuck flat, reading out of physical range, sudden jump, stopped updating). If every check is clean, one “Passed” bullet. Do not invent findings.
2. **Anomaly screening second, high-level only.** One bullet per varying trend: “looks normal”, “needs a look”, or “skipped — not enough fan-on data”. If something needs a look, add one everyday sentence about the trace (for example a sudden dropout). Do not treat that sentence as an equipment fault. No method names.
3. **Executive summary** that opens with the sensor-check outcome and the plain anomaly outcome, then confirmed operating findings rounded to 1 decimal.
4. RCx week line plots for mapped AHU timeseries presets, plus the econ temps overlay and BAS/web overlay when web OAT exists. Mixed units stay on dual axes inside those helpers.
5. Confirmed operating-fault figures only (not the SV bullets). Under each figure, two bullets from `reporting.rule_meta`: what the rule means (`rule_summary`) and what the data shows.
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
| `single_system` / `building` | device folder or building folder of devices | `open-fdd-anomaly report` → `report.typ` (does not replace the row above) |
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
