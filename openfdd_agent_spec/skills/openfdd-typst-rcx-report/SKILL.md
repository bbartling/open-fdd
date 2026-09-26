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
| `single-system` | One device folder (`history_wide.csv` + `column_map.json`), v1 focus `AHU_1` | `open-fdd-anomaly report ./AHU_1 --out ./ahu1_report` |
| `building` | Parent folder of device subfolders. AHU IO is reported; VAV/other children are skipped in the summary | `open-fdd-anomaly report ./BUILDING --scope building --out ./bldg_report` |

Module: `open_fdd/reporting/single_system_typst.py`. Requires `open-fdd[anomaly]`
(pandas oracle rules + screening). Optional PDF: `typst compile report.typ report.pdf`
or `--compile` when `typst` is on `PATH`.

Ordered sections (do not promote anomaly minutes to faults):

1. Data health / quality (role coverage and physical bounds).
2. Sensor-validation oracle (`SV-RANGE`, `SV-FLATLINE`, `SV-SPIKE`, `SV-STALE`) when roles exist.
3. Anomaly scoreboard. Unsupervised ≠ FDD. Fan-ON share is a note; cookbook FC1/economizer gates still do the fan-ON proof.
4. FC1 duct-static / fan evidence (pressure on one axis, fan % on the other).
5. Economizer cookbook rows (`FC2`, `FC3`, `FC10`, `FC11`, `ECON-1`, `ECON-2`, `ECON-4`).
6. Fan-on `economizer_delta_scatter` only. **x = OAT − RAT** (`delta_or_f`), **y = MAT − RAT** (`delta_mr_f`). Reference lines are y = OA fraction × x for 0/25/50/75/100% OA. Fan ON and |OAT−RAT| ≥ 10°F. Build the points with `build_economizer_delta_points` and render with `economizer_delta_scatter`. **Do not plot OAT−MAT vs RAT−MAT.**

Haystack exports store devices under `equip` (object). Flat sidecars use string `equip` plus top-level `points`. Both must resolve or the scoreboard is empty.

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
