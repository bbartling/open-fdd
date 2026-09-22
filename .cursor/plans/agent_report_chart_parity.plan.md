---
name: Agent report chart parity
overview: "Deep eval and fix: PyPI/Typst AI-agent PDF charts must one-for-one match Open-FDD React Plotly (colors, axes, series types). Parallel Wave U W-CHART; PyPI bump when fixes land."
todos:
  - id: chart-inventory
    content: "Inventory React Plotly charts + PyPI/Typst/matplotlib/plotly report figures into a parity matrix"
    status: in_progress
  - id: chart-eval
    content: "Per-chart eval: colors hex, line styles, axis titles/units, scatter vs line/bar, legend, markers"
    status: pending
  - id: chart-fix
    content: "Align PyPI chart theme/helpers to React SoT; regenerate Typst embeds"
    status: pending
  - id: chart-tests
    content: "Permanent known-answer tests for palette/series/axis/type parity on synthetic fixtures"
    status: pending
  - id: chart-spec-docs
    content: "Update typst-rcx-report skill + agent-context + AGENTS rule for parity-locked chart helpers"
    status: pending
  - id: chart-pypi
    content: "PyPI bump + publish after fixes (4.4.5+ if 4.4.4 already shipped for ECM)"
    status: pending
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

Next: complete matrix for every RCx preset + Inspect + FDD series + report chart_id.
