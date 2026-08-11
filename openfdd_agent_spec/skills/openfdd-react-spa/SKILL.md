---
name: openfdd-react-spa
description: >-
  Maintain the Open-FDD React product SPA (frontend/web → openfdd-web). Use when
  editing Overview, FDD Plots, RCx, Mapping, auth UI, or client Plotly charts
  against central /api (DataFusion).
---

# Open-FDD React SPA

## When to use

- Changing `frontend/web` pages, API clients, or Plotly builders
- Overview / FDD / RCx **UX + presentation** vs vibe19 Streamlit (layout, radios,
  inspect defaults, Plotly stretch) — math stays on Rust `/api`
- Auth/login hygiene for internet-facing UI

## Rules

1. Browser → central Rust `/api` only. Overview data from `/api/analytics/*`
   via `fetchCentralOverview` — never invent a pandas/oracle product path.
2. FDD math stays in DataFusion SQL (`sql_rules/`). TypeScript builds figures only.
3. Shared palette: `frontend/web/src/api/plotlyTheme.ts` (`RAINBOW_PALETTE`).
4. No bench secrets, credential paths, or privileged username prefill on login.
5. Prefer Vitest unit tests next to changed modules; Playwright for smoke when needed.
6. Do not add Python to the product SPA or depend on `open_fdd` at runtime.
7. vibe19 is the **UX oracle** (structure, labels, Plotly stretch). Brand stays
   **Open-FDD**. Keep **Update analytics** and **Run all rules** — do not restore
   a Run Rules tab.
8. Overview selection contract:
   - Top **Equipment** defaults to the first natural-sorted id (`AHU_1` before
     `AHU_10`); no empty placeholder.
   - Equipment change updates metrics + inspect pick + inspect refetch (all
     plottable columns). It must **not** filter or wipe building Plotly
     (motor / economizer / OAT — all AHUs stay on the figure).
   - AHU overlay select updates overlay traces only. Site-clear
     `useEffect` depends on `buildingId` only — never `econOverlayEq`.
   - Inspect remounts via `figureId=overview-inspect-{eq}`; columns default to
     **all** plottable roles (vibe19 `default=numeric_cols`).
9. RCx: auto-run when mechanical family / plot changes; unique `figureId` per
   preset; AHU timeseries keep every unit on one figure.
10. FDD Plots: equipment from full inventory (`listFddEquipment`); default rule
    via `_preferred_plot_rule_id` (FAULT/WARNING first); auto-load series;
    status filter radios All / FAULT / PASS / SKIPPED; `figureId={device}_{rule}`.
11. PlotlyHost: `autosize` + ResizeObserver → `Plotly.Plots.resize`; host is
    100% of the content column.

## Key files

| Area | Path |
| --- | --- |
| Overview assembly | `frontend/web/src/api/centralOverview.ts` |
| Overview UI | `frontend/web/src/components/OverviewPopulated.tsx`, `OverviewHero.tsx` |
| Overview types | `frontend/web/src/api/overviewTypes.ts` |
| RCx page | `frontend/web/src/pages/RcxPage.tsx` |
| FDD Plots | `frontend/web/src/pages/ReportsPage.tsx` |
| RCx / FDD charts | `frontend/web/src/api/vibeCharts.ts` |
| Plotly host | `frontend/web/src/components/widgets/PlotlyHost.tsx` |
| Theme | `frontend/web/src/api/plotlyTheme.ts` |
| SPA shell | `frontend/web/src/App.tsx`, `components/` |

## Anti-patterns

- Calling removed overview-oracle endpoints
- Computing fault logic in the browser beyond presentation masks
- Hardcoding purple/glow “AI slop” themes that fight product CSS tokens
- Clearing all Overview analytics when the economizer overlay AHU changes
- Defaulting inspect to the first N columns (must be all plottable)
- Building FDD equipment lists only from rows that already have results
