---
name: openfdd-react-spa
description: >-
  Maintain the Open-FDD React product SPA (frontend/web → openfdd-web). Use when
  editing Overview, Inspect, FDD Plots, RCx, Mapping, Operations, Sites, auth UI,
  health matrices, or client Plotly charts against central /api (DataFusion).
---

# Open-FDD React SPA

## When to use

- Changing `frontend/web` pages, API clients, or Plotly builders
- Overview / FDD / RCx chart parity vs vibe19 **presentation** (colors, axes)
- Operations MQTT monitor / OT strip, Sites inventory
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
7b. **M&V / change-point / savings charts (Wave S):** prefer **Metering**
   (`/metering`) section radios (extend FuelDashboard families) or add one new
   left section radio — never Plotly on Overview. Data from DataFusion
   `/api/analytics/*` (or future M&V SQL routes) only; PyPI/`camber` oracle stays
   off the SPA request path. Update this skill + `AGENTS.md` when adding radios.
8. Sidebar brand shows `GET /api/health` `semver+shortsha` (`data-testid="app-revision"`).
   Collapsed sidebar: `+shortsha` only.
9. After Lab **Update this rule** (`RULES_UPDATED`), FDD Plots / Reports must
   refetch results + series so `confirm_min` session overlays show up.
10. Do not drop `REQUIRED_RCX_PRESET_IDS`. Health row tint uses existing
    `--health-broken-1/2/3` tokens (`n/3`; `?/3` is not red).
11. **Operations** (`/operations`) stays its own main tab — not nested under Sites.
    MQTT console watches Central’s ingest buffer (`GET /api/mqtt/monitor`) — no
    operator-facing scrape/poll-interval knobs (fieldbus owns OT cadence). OT strip
    may surface `/api/ingest/stats` + `/api/edges`. Never put broker credentials in
    the browser.
12. **Sites** (`/sites`) is package/edge **inventory**. CSV / MQTT / Both is an
    operator label only — not a dual-writer historian epic.
13. Low-RAM benches: prefer `npm run dev` (Vite → `:8080`) and get human approval
    before GHCR `openfdd-web` fresh pulls after UI PRs.
14. **Rule display names:** one contract across sidebar, FDD Plots, plot titles, health
    matrices, and exports — see [`docs/RULE_DISPLAY_NAMES.md`](../../docs/RULE_DISPLAY_NAMES.md).
    Registry `description` is canonical short name; cookbooks add long titles. Use shared
    `ruleLabels` helpers (planned); merge `GET /api/fdd/rules` into `cookbookRuleCatalog`
    at boot instead of duplicating static maps.
15. **Site-switch performance (Wave O7):** Cache Overview + health per `buildingId`.
    Do **not** re-fan-out all analytics POSTs on every `?site=` change or thrash
    matrices twice. Invalidate on `RULES_UPDATED` / existing explicit refresh only.
    Prefer durable `GET /api/fdd/results` for flags. Serving SPA from Rust does
    **not** fix this — packaging ≠ UX.
16. **No agent UI chrome:** Never add banners, tips, or “we optimized / cached /
    AI …” copy to explain under-hood work. Keep the product quiet and professional.
    Put rationale in `openfdd_agent_spec` / PR description, not the SPA.
17. **Hub Admin (Wave O8):** `/admin` is hub_admin only — quiet tables for users/tenants.
18. **Data Model export (Wave O9):** Export = **entire active site** data model JSON.
    Do not offer device/point-scoped export. Equipment picker is for edits only.
    Foreign `building_id` must 403 for non-admin (mapping, model download, session config).

## Key files

| Area | Path |
| --- | --- |
| Overview assembly | `frontend/web/src/api/centralOverview.ts` |
| Overview types | `frontend/web/src/api/overviewTypes.ts` |
| Health matrices | `frontend/web/src/components/HealthMatrixSection.tsx` |
| Inspect | `frontend/web/src/pages/InspectPage.tsx` |
| Operations | `frontend/web/src/pages/OperationsPage.tsx` |
| Sites | `frontend/web/src/pages/SitesPage.tsx` |
| RCx Overview presets | `frontend/web/src/api/rcxOverviewPresets.ts` |
| RCx / FDD charts | `frontend/web/src/api/vibeCharts.ts` |
| Theme | `frontend/web/src/api/plotlyTheme.ts` |
| Rule labels | `frontend/web/src/lib/cookbookRuleCatalog.ts`; planned `lib/ruleLabels.ts` |
| SPA shell | `frontend/web/src/App.tsx`, `components/` |

## Anti-patterns

- Calling removed overview-oracle endpoints
- Computing fault logic in the browser beyond presentation masks
- Hardcoding purple/glow “AI slop” themes that fight product CSS tokens
- Putting Plotly motor/mech/econ/BAS hosts back on Overview
- Nesting Operations under Sites or treating Sites ingest labels as backend mode
- Exposing MQTT broker secrets to the SPA
- Shipping GHCR web without Vite operator approval on low-RAM benches when required by the active plan
- Adding goofy explanatory UI text for agent/under-hood changes
- Clearing Overview and re-running all DataFusion analytics on every building switch
