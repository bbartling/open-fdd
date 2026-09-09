---
name: openfdd-typst-rcx-report
description: >-
  Build engineer-facing Typst RCx lab PDFs from live DataFusion Overview / RCx /
  FDD series APIs (VAV AHU systems). Use when the user asks for an RCx lab report,
  BUILDING_100 screening pack, Typst PDF from Railway analytics, FC1/SATDEV/ECON
  fault overlays, Overview health tables in PDF/Excel, or agent lab report (not
  rust-text-pdf). Triggers on: typst rcx, rcx lab report, VAV AHU report,
  confirmed_fault overlay PDF, building100_rcx_report.
---

# Open-FDD Typst RCx lab report (VAV AHU)

**Not** the product PDF path (`rust-text-pdf`). Agent lab screening pack:
DataFusion → Plotly (UI palette) → Typst → PDF + Overview CSVs for Excel.

Reference kit: `/home/ben/building100_rcx_report/`.

## When to use

- **VAV AHU** RCx / Overview screening PDF from Railway (or any hub)
- Per-AHU **FC1**, **AHU-SATDEV**, **FC13-SAT-HIGH**, **ECON-*** with
  **`confirmed_fault` swim lane**
- Overview health matrices as **tables** (not heatmaps) + Excel CSVs
- Engineer narrative (system type, data volume/freq, RCx insights) — **no** IT method section

## Hard rules

1. **Data model driven** — only plot Overview / RCx / FDD payloads. Empty = missing roles (`openfdd-package-mapping`).
2. **Colors** — `RAINBOW_PALETTE` (`frontend/web/src/api/plotlyTheme.ts`).
3. **Line gaps (adaptive)** — null **Y only** (`connectgaps=False`). Gap threshold =
   `max(3600, 4 × median_Δt)` — **never** fixed 900s after span-preserving downsample
   (~25 min spacing would blank every point).
4. **Full historian span** — line plots from `POST /api/analytics/inspect`
   (`max_points: 8000`, span-preserving). Merge `confirmed_fault` from
   `GET /api/fdd/series` by timestamp. Until hub tip has span-preserving FDD series,
   fault lane may be sparse (series still recent-only on ops pin).
5. **FDD overlays** — `FC1`, `AHU-SATDEV`, `FC13-SAT-HIGH`, faulted `ECON-*`.
6. **PDF layout** — snapshot + insights → **charts by plot type** (both AHUs under each
   chart family) → Overview tables **last**. FDD fault-hours bars = **rule × equipment**
   labels + caption listing drivers.
7. **Overview tables** — UI columns in PDF + `tables/*.csv` for Excel.
8. **Product boundary** — do not replace `rust-text-pdf`; no Plotly on SPA Overview.
9. **Low-RAM** — no local stack `docker build`; fetch live hub JWT.

## Known product bugs (document + patch; lab workarounds above)

Log in `docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md` and Wave K master:

| ID | Defect | Patch location |
|----|--------|----------------|
| **fdd-series-recent-only** | `DESC LIMIT 5000` → last ~2 weeks only | `edge/src/fdd/registry_api.rs` span-preserving 8k |
| **econ-points-prefix-limit** | economizer points prefix LIMIT | `historian::economizer_from_history` ranked sample |
| **rcx-oat-scatter-cap** | OAT scatter clamp 12k truncates season | `rcx_oat_scatter_from_history` → 20k |

Working-tree patches may exist before tip Publish — do **not** claim hub fixed until
Railway re-pin + smoke. Wave K: ship with / right after K1 tip.

## Pipeline

```text
fetch_railway.py    → data/*.json (+ inspect_* + fdd_series_*)
render_plots.py     → figures/*.png + tables/*.csv + fdd_fault_hours_caption.md
build_typst_body.py → generated_snapshot.typ + generated_tables.typ + generated_fdd_caption.typ
typst compile main.typ BUILDING_<ID>_RCx_Lab_Report.pdf
```

Auth: `POST /api/auth/login` + Railway `OPENFDD_ADMIN_PASSWORD` (central).

### Required fetches (VAV AHU)

| Surface | Endpoint |
|---------|----------|
| Runtime / mech / econ / BAS | `POST /api/analytics/{runtime,mechanical-cooling,economizer,bas-vs-web-oat}` max_points≥8000 |
| Inspect (full-span lines) | `POST /api/analytics/inspect` per AHU, columns sat/mat/rat/oa_t/damper/fan/duct/sat_sp |
| Health matrices | `POST /api/analytics/ahu-*-health`, chiller, boiler, pid, sensor, vav, … |
| RCx scatters / rank | `POST /api/analytics/rcx/preset` with max_points≤20000 |
| FDD overlays | `GET /api/fdd/series` AHU × `{FC1,AHU-SATDEV,FC13-SAT-HIGH,ECON-*}` |
| Inventory | equipment, mapping, `GET /api/fdd/results` |

SPA intercepts some RCx ids (`ahu_motor_weekly`, `mech_cooling_oat_bins`, `bas_vs_web_oat`) —
use Overview analytics POSTs for those charts.

### Site snapshot + insights

HVAC type, equipment counts, history window, ~5-min frequency, historian row volume,
plant motor hours. RCx advice separates **data** faults from **HVAC** faults.

## Figure checklist (dual VAV AHU)

- [ ] Zone comfort; weekly runtimes air/boiler/chiller; mech OAT bins; BAS vs web
- [ ] HW / CHW / SAT scatters
- [ ] FDD fault hours **rule × equipment** + caption
- [ ] Economizer Δ / MAT residual / temps (plot-type groups, both AHUs)
- [ ] FC1 / AHU-SATDEV / FC13-SAT-HIGH / ECON-1 / ECON-4 overlays (both AHUs)
- [ ] Overview health tables after charts; `tables/*.csv`

## Anti-patterns

- Fixed 15-min gap on downsampled series (blanks the plot)
- Inserting `None` into **X** timestamps (collapses traces)
- Heatmap health flags; anonymous rule bars without equipment
- AHU-first then all chart types (prefer plot-type-first)
- IT method / JWT / Kaleido section for engineers
- Claiming hub FDD series is full-span before tip re-pin

## Related

- `openfdd-react-spa` · `openfdd-package-mapping` · `openfdd-ecm-engineering` · `openfdd-railway-cli`
- Wave K plan + BUG_REPORT plot-span OPEN rows
