---
name: openfdd-react-spa
description: >-
  Maintain the Open-FDD React product SPA (frontend/web → openfdd-web). Use when
  editing Overview, Inspect, FDD Plots, RCx, Mapping, auth UI, health matrices,
  or client Plotly charts against central /api (DataFusion).
---

# Open-FDD React SPA

## When to use

- Changing `frontend/web` pages, API clients, or Plotly builders
- Overview / FDD / RCx chart parity vs vibe19 **presentation** (colors, axes)
- Auth/login hygiene for internet-facing UI

## Rules

1. Browser → central Rust `/api` only. Overview data from `/api/analytics/*`
   via `fetchCentralOverview` — never invent a pandas/oracle product path.
2. FDD math stays in DataFusion SQL (`sql_rules/`). TypeScript builds figures only.
3. Shared palette: `frontend/web/src/api/plotlyTheme.ts` (`RAINBOW_PALETTE`).
4. No bench secrets, credential paths, or privileged username prefill on login.
5. Prefer Vitest unit tests next to changed modules; Playwright for smoke when needed.
6. Do not add Python to the product SPA or depend on `open_fdd` at runtime.
7. **Overview = tables + health matrices** (AHU / chiller / boiler / HP / VAV).
   No Plotly on Overview. Motor / mech / econ / BAS figures are additive RCx
   presets. CSV overlay lives on **Inspect** (`/inspect`). Empty charts mean
   missing zip roles — see [`openfdd-package-mapping`](../openfdd-package-mapping/SKILL.md).
8. Sidebar brand shows `GET /api/health` `semver+shortsha` (`data-testid="app-revision"`).
   Collapsed sidebar: `+shortsha` only.
9. After Lab **Update this rule** (`RULES_UPDATED`), FDD Plots / Reports must
   refetch results + series so `confirm_min` session overlays show up.
10. Do not drop `REQUIRED_RCX_PRESET_IDS`. Health row tint uses existing
    `--health-broken-1/2/3` tokens (`n/3`; `?/3` is not red).

## Key files

| Area | Path |
| --- | --- |
| Overview assembly | `frontend/web/src/api/centralOverview.ts` |
| Overview types | `frontend/web/src/api/overviewTypes.ts` |
| Health matrices | `frontend/web/src/components/HealthMatrixSection.tsx` |
| Inspect | `frontend/web/src/pages/InspectPage.tsx` |
| RCx Overview presets | `frontend/web/src/api/rcxOverviewPresets.ts` |
| RCx / FDD charts | `frontend/web/src/api/vibeCharts.ts` |
| Theme | `frontend/web/src/api/plotlyTheme.ts` |
| SPA shell | `frontend/web/src/App.tsx`, `components/` |

## Anti-patterns

- Calling removed overview-oracle endpoints
- Computing fault logic in the browser beyond presentation masks
- Hardcoding purple/glow “AI slop” themes that fight product CSS tokens
- Putting Plotly motor/mech/econ/BAS hosts back on Overview
