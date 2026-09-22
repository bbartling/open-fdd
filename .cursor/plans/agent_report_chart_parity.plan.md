---
name: Agent report chart parity
overview: "Deep eval and fix: PyPI/Typst AI-agent PDF charts must one-for-one match Open-FDD React Plotly (colors, axes, series types). Parallel Wave U W-CHART; PyPI bump when fixes land."
todos:
  - id: chart-inventory
    content: "Inventory React Plotly charts + PyPI/Typst/matplotlib/plotly report figures into a parity matrix"
    status: completed
  - id: chart-eval
    content: "Per-chart eval: colors hex, line styles, axis titles/units, scatter vs line/bar, legend, markers"
    status: in_progress
  - id: chart-fix
    content: "Align PyPI chart theme/helpers to React SoT; regenerate Typst embeds"
    status: in_progress
  - id: chart-tests
    content: "Permanent known-answer tests for palette/series/axis/type parity on synthetic fixtures"
    status: in_progress
  - id: chart-spec-docs
    content: "Update typst-rcx-report skill + agent-context + AGENTS rule for parity-locked chart helpers"
    status: completed
  - id: chart-pypi
    content: "PyPI bump + publish after fixes (4.4.6 Inspect/stems; tag after merge)"
    status: in_progress
isProject: false
---

# Agent report chart parity (PyPI/Typst vs React Plotly)

**Parent:** [wave_u_post-fq_remainder.plan.md](wave_u_post-fq_remainder.plan.md) cycle **W-CHART** (parallel; does not block W1–W3).

**Problem:** AI agents produce Engineering Findings / RCx PDF reports via **PyPI** (`open_fdd.reporting`, Typst app). Charts are close to the product **React Plotly** UI but often look worse — muted/wrong colors, axis drift, scatter vs line mismatches. React Plotly is the visual source of truth for product-facing series; agent PDF figures should match within documented PDF constraints (DPI, page width).

## Evaluation checklist (every chart)

For each `chart_id`:

| Check | Pass criteria |
| --- | --- |
| Chart type | Same family (scatter / line / bar / heatmap) as React |
| Series set | Same roles/series ids in same order |
| Colors | Hex one-for-one with React theme / series color map |
| Line style | Solid/dash/width match (or documented PDF tolerance) |
| Markers | Presence/size/symbol match when React uses markers |
| X/Y axes | Titles, units (°F/°C, %, kW), range policy, secondary axis |
| Legend | Labels match React display names |
| Overlay / multi-y | Dual-axis assignment matches Inspect/FDD/RCx |
| Filename stem | `downloadFilename` / Typst asset stem documented |

Do **not** mark COMPLETE from “looks okay” screenshots alone — capture matrix + permanent tests.

## Surfaces to inventory

**React (SoT):** `frontend/web` — RCx Plots presets, Inspect CSV overlay, FDD Plots series, motors, mixing/economizer, mech OAT bins, weather/anomaly if charted.

**PyPI / Typst (agent):** `open_fdd/reporting`, `open_fdd/analytics` figure helpers, Typst templates / PNG exporters, skills `openfdd-typst-rcx-report`, ECM/Findings docs.

## Early evidence (2026-09-22 inventory start)

| Surface | Path | Notes |
| --- | --- | --- |
| React SoT palette | `frontend/web/src/api/plotlyTheme.ts` `RAINBOW_PALETTE` | 12 hex colors; shared with vibe19 |
| PyPI analytics Plotly | `open_fdd/analytics/charts.py` `RAINBOW_PALETTE` | **Same hex list** as React (good baseline) |
| React figure builders | `frontend/web/src/api/centralOverview.ts`, RCx/Inspect/FDD pages + `PlotlyHost` | Motors, mixing, OAT bins, bas hist, etc. |
| Agent report charts | `open_fdd/reporting/charts.py`, `overview_export.py`, `day_zoom.py` | Findings bars use **`#2b6cb0`** (not rainbow); day-zoom is **matplotlib** |
| Typst skill | `openfdd_agent_spec/skills/openfdd-typst-rcx-report/SKILL.md` | Agent PDF entry |

**Suspected gaps (to prove with matrix + tests):**

1. Findings horizontal fault-hours bars: fixed blue vs React rainbow / product bar colors.
2. Day-zoom matplotlib PNGs: different renderer → color/axis/line quality vs Plotly Inspect/FDD.
3. Overview export may call analytics helpers (parity better) but PDF width/DPI may still look “less nice”.
4. Any Typst-embedded assets that recolor or restyle after export.

Next: permanent palette lock test + day_zoom/report color alignment; expand `charts.contract.json`.

## Parity matrix (inventory 2026-09-22)

React SoT builders: `vibeCharts.*`, `centralOverview.*`, `inspectChart.*`, `fuelCharts.*`, `MvChangePointPanel`.  
PyPI: `open_fdd/analytics/charts.py`, `reporting/overview_export.py`, `reporting/charts.py`, `reporting/day_zoom.py`.  
Typst kit (out-of-tree): `/home/ben/building100_rcx_report/` per typst skill.

| chart_id | React | PyPI | Gap |
| --- | --- | --- | --- |
| `fdd_rule_result` | `vibeCharts.ruleResultChart` | `charts.rule_result_chart` | Mostly aligned; React sets title + date axis |
| `fdd_oat_meteo_overlay` | `withConfirmedFaultLane`+`basOverlay` | `bas_vs_web_oat_overlay` | Compose path differ |
| `sensor_fault_chart` | `vibeCharts.sensorFaultChart` | `charts.sensor_fault_chart` | Swim-lane domains |
| `sensor_health_heatmap` | `vibeCharts.sensorHealthHeatmap` | **missing** | React-only |
| `inspect_stacked` | `inspectChart.equipmentInspectionChart` | `equipment_inspection_chart` | **CLOSED 4.4.6** — stacked domains + `Inspection —` title; Soft-OPEN: PDF DPI/width only |
| `rcx_timeseries_*` | `multiEquipmentTimeseries` | `multi_equipment_timeseries` | Fault-lane forbidden on RCx |
| `rcx_scatter_oat_*` | `oatScatter` | `oat_scatter` | Markers vs lines |
| `rcx_box_*` | `multiEquipmentBox` | `multi_equipment_box` | Outlier markers |
| `rcx_ranking` / comfort | `rankingBars`+`comfortDonut` | `vav_comfort_donut` + report bars `#c05621` | Report chrome ≠ UI |
| `vav_health_matrix` | `vavHealthWorstBars`/`Donut` | **no twin** | React-only |
| `rcx_metering` | `meteringCharts` | bar + degree-day scatter | Combined vs split figs |
| `*_motor_weekly` | `weeklyPlantFigures` | `motor_weekly_runtime_chart` | React bare stem; PyPI Soft-OPEN `overview_motor_weekly_*` |
| `mech_cooling_oat_bins` | `mechFigure` | `mech_cooling_oat_histogram` | Stem vocab locked in contract |
| `economizer_*` | `econDeltaScatter` / mat / temps | matching `economizer_*` | Dual-axis temps critical |
| `bas_vs_web_oat` | overlay + `basHist` | overlay + histogram | Companion stem `bas_web_oat_deviation_hist` |
| `fuel_*` | `fuelCharts.ts` (12) | partial metering | **CLOSED** React `downloadFilename`; PyPI twin Soft-OPEN |
| `mv_changepoint` | `MvChangePointPanel` | ECM oracle | By-design diverge |
| `report_*` / `day_zoom` | none | `reporting/charts.py`, `day_zoom.py` | day_zoom rainbow **CLOSED 4.4.5**; Findings bars Soft-OPEN `#2b6cb0` |

**Highest-risk fixes first:** (1) palette lock React↔PyPI JSON — **DONE 4.4.5**; (2) day_zoom → `RAINBOW_PALETTE` — **DONE 4.4.5**; (3) PNG stem vocabulary — **DONE 4.4.6** (React bare + PyPI Soft-OPEN `overview_*`); (4) Inspect title/axis — **DONE 4.4.6**; (5) Fuel `downloadFilename` — **DONE**.

## Soft-OPEN (chart) after 4.4.6

- Findings / report chrome bars (`#2b6cb0` / `#c05621`) vs rainbow — document or align later
- PyPI `overview_*` PNG name prefix vs React bare stems (intentional Typst alias)
- `sensor_health_heatmap` / `vav_health_matrix` React-only twins
- Dual-axis economizer / OAT scatter marker-vs-line polish
- PDF DPI / page-width rendering deltas vs Plotly web

## Exit

A fresh agent following updated skills produces PDF charts that pass the permanent parity tests against React color/axis/type fixtures; Soft-OPEN rows list any intentional PDF-only deltas with measured tolerances. PyPI version published.
