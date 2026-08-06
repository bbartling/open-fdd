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

## Key files

| Area | Path |
| --- | --- |
| Overview assembly | `frontend/web/src/api/centralOverview.ts` |
| Overview types | `frontend/web/src/api/overviewTypes.ts` |
| RCx / FDD charts | `frontend/web/src/api/vibeCharts.ts` |
| Theme | `frontend/web/src/api/plotlyTheme.ts` |
| SPA shell | `frontend/web/src/App.tsx`, `components/` |

## Anti-patterns

- Calling removed overview-oracle endpoints
- Computing fault logic in the browser beyond presentation masks
- Hardcoding purple/glow “AI slop” themes that fight product CSS tokens
