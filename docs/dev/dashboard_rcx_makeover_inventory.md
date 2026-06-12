# Dashboard + RCx Makeover — Inventory

Branch: `feature/dashboard-rcx-mega-makeover`  
Date: 2026-05-30

## What exists

| Area | Location | Notes |
|------|----------|-------|
| React operator dashboard | `workspace/dashboard/` | Vite + React 19, theme via `contexts/theme-context.tsx`, CSS vars |
| Plotly charts | `lib/plot-chart.ts`, `PlotPage.tsx`, `HostStatsPage.tsx` | Partial theme handling; not centralized |
| Building check-engine | `building_status.py`, `FaultsPage`, `BuildingInsightDashboard` | Single source for alerts |
| FDD batch + analytics | `fdd_results.py`, `fdd_fault_analytics.py` | Per-run sample analytics, equipment enrichment |
| Poll / model health | `poll_throughput.py`, `model_health.py`, `device_poll_health.py` | Used by agent, not dashboard analytics pages |
| Zone temp analytics | `zone_temp_analytics.py` | VAV comfort metrics via agent routes |
| Central RCx DOCX | `portfolio/central/rcx_report.py`, `fault_hours.py` | Central-only (`POST /api/central/rcx/report`) |
| Generic open_fdd reports | `open_fdd/reports/docx_generator.py`, `fault_viz.py` | Equipment FDD reports, optional deps |
| Portfolio desk | `portfolio/dash/app.py`, `portfolio/central/api.py` | Separate Dash + FastAPI stack |
| Frontend unit tests | 14 Vitest files under `workspace/dashboard/src/lib/` | Not in CI |
| Bridge Python tests | `tests/workspace_bridge/`, `tests/portfolio/` | Strong coverage for building insight, central |

## What partially exists

- **Theme toggle** — app shell updates; Plotly uses inline colors in `plot-chart.ts` / `HostStatsPage.tsx` (inconsistent).
- **Fault display** — equipment names in check-engine alerts when model maps columns; catalog page is not analytics-focused.
- **RCx DOCX** — portfolio central builder with basic sections; not exposed on edge bridge; no chart/section checkboxes.
- **Fault hours** — `portfolio/central/fault_hours.py` estimates from rollups; FDD run analytics has duration estimates but no REST aggregation.
- **Demo data** — `workspace/data/acme_gl36_model.json`, `fdd_results.json`, `samples/demo_site.csv`; no unified analytics fixture.

## What is missing (this branch targets)

- Shared `getPlotlyThemeLayout()` helper + all charts using it
- Analytics pages: Overview, Fault Analytics, Equipment, BACnet/Model Health, RCx Report Builder
- Bridge REST: `/api/analytics/overview`, `/faults`, `/equipment/{id}`, `/model-health`, `/reports/rcx/preview`, `/reports/rcx/generate`
- Edge RCx DOCX with selectable sections/charts (`open_fdd/reports/rcx_docx.py`)
- Fault-hour aggregation module with tests
- Demo analytics fixture for CI
- Docs: `docs/dashboard-analytics.md`, `docs/rcx-report-builder.md`

## Files inspected

```
AGENTS.md, README.md, pyproject.toml
workspace/dashboard/src/App.tsx, AppLayout.tsx, theme-context.tsx, plot-chart.ts
workspace/api/openfdd_bridge/main.py, building_status.py, fdd_results.py, fdd_fault_analytics.py
workspace/api/openfdd_bridge/routes/analytics_routes.py
portfolio/central/rcx_report.py, fault_hours.py, api.py
open_fdd/reports/
tests/workspace_bridge/, tests/portfolio/test_central.py
```

## Recommended implementation path

1. **Foundation** — `open_fdd/reports/fault_hours.py`, `charts.py`, `rcx_docx.py`; bridge `dashboard_analytics.py` + routes; deps in bridge requirements.
2. **Theme** — `plotly-theme.ts`; refactor `plot-chart.ts` + `HostStatsPage.tsx`.
3. **UI** — Analytics nav section + pages wired to new APIs; RCx Report Builder with preview/generate.
4. **Fixtures + tests** — demo JSON, backend pytest, Vitest for theme + report builder.
5. **Docs** — operator-facing how-to.

## Known risks

- **Scope** — full prompt is multi-PR; this branch delivers edge dashboard + bridge RCx; Central Dash remains separate.
- **Live BACnet** — analytics read persisted FDD/model/poll data only (read-only).
- **Trend charts in RCx** — need timeseries API + point roles; may be partial when historian empty.
- **ACME coupling** — use demo fixture + model-driven roles, not hard-coded point names.
