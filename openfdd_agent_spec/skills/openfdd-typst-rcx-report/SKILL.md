---
name: openfdd-typst-rcx-report
description: >-
  Build engineer-facing Typst lab PDFs from live DataFusion Overview / RCx /
  Inspect APIs. Covers VAV AHU (BUILDING_100), heat-pump + metering (LAKESIDE_ES /
  Creekside), and MQTTS zone monitoring (bldg2). CRITICAL: preserve Overview-
  mirrored charts; never strip reports to thin package layouts. Triggers on:
  typst rcx, rcx lab report, heat pump report, lakeside, creekside, mqtts zone
  PDF, building100_rcx_report, elec_power metering PDF, box plot, seasonal heat cool.
---

# Open-FDD Typst lab reports (multi-profile)

**Not** the product PDF path (`rust-text-pdf`). Agent lab screening pack:
DataFusion → Plotly (UI palette) → Typst → PDF + CSVs for Excel.

Reference kit: `/home/ben/building100_rcx_report/`.

**PyPI staging (not in open-fdd master yet):** package `open-fdd-lab-typst`
(`openfdd_lab_typst`, CLI `open-fdd-lab-typst`). Future monorepo path
`open_fdd.lab_typst` — see kit `FUTURE_OPENFDD_MERGE.md`.

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
