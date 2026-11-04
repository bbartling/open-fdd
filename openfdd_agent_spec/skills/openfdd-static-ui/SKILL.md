---
name: openfdd-static-ui
description: >-
  Maintain Open-FDD Central — static product UI on central (`services/central/static/product`,
  served at `/app/`; default portal compose sets OPENFDD_STATIC_PRODUCT_UI=1).
  Bench Viz layout, light blueprint + dark toggle, vendored ECharts, chart-parity matrix.
---

# Open-FDD Central (static product UI on `/app/`)

## When to use

- Editing `services/central/static/product/` (HTML, CSS, JS) or `static_product.rs`
- RCx / FDD plot parity vs archived React SPA (`archive/product-ui/react-spa-v4`)
- Chart themes, PNG download stems, fault swim lane, Overview RCx fidelity
- Model tree + SPARQL (TTL-only on Model tab)
- CSV upload/export, hub admin read surfaces, synthetic M&V demo (Ops tab)
- Vendoring chart libraries under `assets/vendor/`

## Rules

1. **Same-origin `/api` only** — no CDN scripts, no `/api/v1`, no inline `style=""` or non-module scripts.
2. **CSP** — product CSP is `script-src 'self'` without `unsafe-inline` / `unsafe-eval`. Product JS must not call `eval` or `new Function`. ECharts ships full build; use canvas renderer paths exercised by RCx/FDD/Inspect charts only.
3. **Model tab** — tree and checks from **`GET /api/model/ttl`** and **`POST /api/model/sparql`** only. Do not call `/api/model/agent-context` on Model pages.
4. **Operational data** — historian points, package mapping, FDD session config, analytics, and FDD run/plot use existing `/api` routes from `site-data.js`, `rcx-presets.js`, `fdd-api.js`.
5. **ECharts** — vendored under `assets/vendor/` with `.version` sidecar + `LICENSE.echarts.txt`. Pin latest stable; update sidecar when replacing files.
6. **Themes** — `assets/js/chart-theme.js` registers `ofdd-light` (blueprint) and `ofdd-dark` (Bench Viz). Default is **light**; header toggle persists in `localStorage` (`openfdd-ui-theme`). `mountChart` re-inits on toggle. CSS tokens: `bench.css` `:root` + `[data-theme="dark"]`.
7. **Renderers** — return theme-free ECharts options (no hardcoded `#c9d2e8` / `#8899bb` in chart modules). Use `rainbowColor`, `toolboxSaveAsImage(stem)`.
8. **Chart parity** — `services/central/static/product/chart-parity.json` maps each archived Plotly builder → JS export + PNG stem. **Adding or changing a chart requires updating the matrix and a shape test** in `assets/js/*.test.mjs` (`node --test services/central/static/product/assets/js/*.test.mjs`).
9. **FDD fault lane** — stacked unit-family grids (`fdd-charts.js#ruleResultChartOption`); bottom `confirmed_fault` grid; `connectNulls: false`; unknown fault → `[t, null]`; OAT-METEO uses weather overlay + lane (`oatMeteoFddOption`). RCx presets must **not** include a fault lane (`rcxOptionHasFaultLane`).
10. **Lean pages** — `index.html`, `tree.html`, `rcx.html`, `fdd.html` link CSS + module scripts only; logic lives in `assets/js/`.
11. **Parity** — match archived SPA behavior for Overview RCx presets, economizer gate (`ECONOMIZER_DT_MIN_C`), `analyticsWindowFromSampling`, FDD status filters, `confirm_min` on run, inspect title/stacking, series preview 10/20/50/100/500. SI storage; metric display default.
12. **Dynamic text** — use `textContent` / DOM APIs; never inject HTML strings from API responses.
13. **Graph projection (Model + Points)** — equipment and points come from the server TTL/SPARQL graph projection (`GET /api/model/ttl`, tree builders in `ttl-model.js` / `tree-view.js`). Point ids are opaque stored series keys; duplicate same-role sensors keep distinct ids. Command roles stay Number when the model declares a numeric unit/kind — do not coerce VFD/command `%` to Bool. Read-only metadata from the graph; no `/api/model/agent-context` on Model pages.
14. **SI units end-to-end** — declared source unit + quantity on ingest/resync; Timescale stores `metric-c-v2`; API returns SI with unit metadata; charts label axes from declared/display conversion (`charts.js`, RCx modules). Missing declarations remain explicit not-assessed / empty states — never silently assume Pa when the model says inH₂O.
15. **Scope guards** — `site-data.js` binds an immutable active site + generation counter; fetches attach `AbortController` and ignore stale responses. Unauthorized `?site=` is rejected (UI + backend tests). Lazy tabs must not fire hidden FDD/RCx work for off-tab sites.
16. **Chart reachability** — every `chart-parity.json` row used in product must expose a visible control, issue a bounded historian/analytics request, adapt timestamps (epoch ms + ISO in FDD preview tables), and render a non-empty chart when data exists. RCx presets exclude the FDD fault swim lane. Rule tuning: authorized save/reset/readback + scoped cache invalidation on `RULES_UPDATED` (`fdd-tab.js`). Residual: explicit calendar date pickers on the Charts tab are not shipped yet (#1510); coverage-aware windows and presets are.

## Chart modules

| Area | Module |
| --- | --- |
| Theme / mount | `chart-theme.js`, `chart-kit.js` |
| FDD plots | `fdd-charts.js` |
| Overview RCx | `overview-rcx-charts.js`, `rcx-presets.js` |
| Generic RCx | `rcx-vibe-charts.js` |
| Fuel | `fuel-charts.js` |
| Sensor | `sensor-charts.js` |
| M&V | `mv-charts.js` |
| Bench Charts tab | `charts.js` |

## Tabs (index.html)

| Tab | Module | APIs |
| --- | --- | --- |
| Overview / Charts / Points | `app.js`, `charts.js` | health, mapping, historian |
| RCx | `rcx-tab.js`, `rcx-presets.js` | `/api/analytics/*` |
| FDD | `fdd-tab.js`, `fdd-api.js` | `/api/fdd/*`, session config |
| Schedules | `schedules-tab.js` | `/api/schedules/status`, ingest gaps, AFDD |
| **Ops** | `operations-tab.js` | CSV import/export, admin read, synthetic M&V |
| Model | `tree-view.js`, `ttl-model.js` | TTL + SPARQL |

## CI smoke (no central image build)

Against a running central with static UI enabled:

```bash
OPENFDD_ADMIN_PASSWORD='…' ./scripts/ci/static_ui_smoke.sh
```

Asset/policy gate: `./scripts/ci/static_product_guard.sh`. Rust asset tests: `cargo test -p openfdd-central 'static_product::'`. JS parity/shape tests:

```bash
node --test services/central/static/product/assets/js/*.test.mjs
```

**Rollback:** `docker/compose.react.yml` + GHCR `openfdd-web`. Set `OPENFDD_STATIC_PRODUCT_UI=0` when running the React container on `:3000`.

## Related

- ADR: [`docs/architecture/adr-013-static-product-ui-central.md`](../../../docs/architecture/adr-013-static-product-ui-central.md)
- Parity matrix: [`services/central/static/product/chart-parity.json`](../../../services/central/static/product/chart-parity.json)
- Archived React reference: [`archive/product-ui/react-spa-v4/`](../../../archive/product-ui/react-spa-v4/)
- [`openfdd-react-spa`](../openfdd-react-spa/SKILL.md) — historical SPA only
