# PR #1488 GitHub description (canonical)

Replace the **entire** GitHub pull request description with the text below (no legacy Summary / Stacked on #1487 / Made with Cursor block above it). Keep **Fixes part of** (never **Closes**).

---

## Wave C static product UI (`/app/`)

Delivers Bench Viz shell on central with TTL model tree, SPARQL, Overview-mirrored **RCx** and **FDD** plots (ECharts **6.1.0** ESM, no CDN), and agent spec updates. Vendored Apache ECharts ships as `echarts.esm.min.js` only (canvas renderer paths for line/bar/scatter, tree, heatmap).

Fixes part of the Wave C static UI program in [ADR-013](../../architecture/adr-013-static-product-ui-central.md) (tracking epic [#1284](https://github.com/bbartling/open-fdd/issues/1284) Soft-OPEN product surfaces).

### CSP verification

- Product JS never calls `eval` / `new Function` (`static_product::static_product_js_avoids_eval`).
- Full ECharts build may contain an unused geoJSON `new Function` path; exercised UI does not load map charts.
- **CI:** `real_stack_browser.sh` runs `e2e/static-product-csp.spec.ts` against `http://127.0.0.1:8080/app/` with `OPENFDD_STATIC_PRODUCT_UI=1` (Overview, Charts, Points, RCx, FDD, Model), waits for tab render markers and chart canvas or explicit empty-state hints, then asserts zero `securitypolicyviolation` events. **Inline JSON check in `real_stack_browser.sh`** fails the job if the Playwright JSON report lists zero tests or any test did not pass.

### Archived SPA → static map

| Feature | Static location |
| --- | --- |
| Analytics POST window + flatten | `analytics.js` — `analyticsBody`; `window-policy.js` — `analyticsWindowFromSampling` |
| Tip envelope normalizer | `tip-analytics-normalize.js` — `normalizeTipOverviewEnvelope`, economizer/BAS/runtime/mech helpers |
| RCx presets | `rcx-presets.js` — `loadOverviewRcxPreset`; UI `rcx-tab.js` — `refreshRcxTab` |
| FDD run / plot / status | `fdd-api.js`, `fdd-status.js`, `fdd-tab.js` |
| Session `confirm_min` | `rule-params.js` — `confirmMinForRule`, `effectiveRunParams`; tests in `rule-params.test.mjs` |
| Series preview | `series-preview.js` — `recentSeriesPreviewFromLines`, `renderPreviewTable` |
| Inspect / FDD charts | `chart-kit.js` — `inspectChartOption`, `fddPlotOption` |
| Model TTL + SPARQL | `ttl-model.js`, `model.js`, `tree-view.js` |

### Bench Viz deferred

Candlestick/box charts, live 15s polling, imperial unit toggle (metric display only).

### Test plan

- `node --test services/central/static/product/assets/js/*.test.mjs`
- `cargo test -p openfdd-central static_product::`
- Real-stack browser job (includes static CSP spec on central `:8080`)

**Do not merge** — Grok merges after green CI.
