---
name: openfdd-static-ui
description: >-
  Maintain the Open-FDD static product UI on central (`services/central/static/product`,
  served at `/app/` when OPENFDD_STATIC_PRODUCT_UI=1). Lean HTML pages, modular JS,
  vendored ECharts (no CDN), same-origin `/api` only, strict CSP without unsafe-eval.
---

# Open-FDD static product UI (central `/app/`)

## When to use

- Editing `services/central/static/product/` (HTML, CSS, JS) or `static_product.rs`
- RCx / FDD plot parity vs archived React SPA (`archive/product-ui/react-spa-v4`)
- Model tree + SPARQL (TTL-only on Model tab)
- Vendoring chart libraries under `assets/vendor/`

## Rules

1. **Same-origin `/api` only** — no CDN scripts, no `/api/v1`, no inline `style=""` or non-module scripts.
2. **CSP** — product CSP is `script-src 'self'` without `unsafe-inline` / `unsafe-eval`. Product JS must not call `eval` or `new Function`. ECharts ships full build; use canvas renderer paths exercised by RCx/FDD/Inspect charts only.
3. **Model tab** — tree and checks from **`GET /api/model/ttl`** and **`POST /api/model/sparql`** only. Do not call `/api/model/agent-context` on Model pages.
4. **Operational data** — historian points, package mapping, FDD session config, analytics, and FDD run/plot may use their existing `/api` routes from `assets/js/site-data.js`, `rcx-presets.js`, `fdd-api.js`.
5. **ECharts** — vendored under `assets/vendor/` with `.version` sidecar + `LICENSE.echarts.txt`. Pin latest stable; update sidecar when replacing files.
6. **Lean pages** — `index.html`, `tree.html`, `rcx.html`, `fdd.html` link CSS + module scripts only; logic lives in `assets/js/`.
7. **Parity** — match archived SPA behavior for Overview RCx presets, economizer gate (`ECONOMIZER_DT_MIN_C`), `analyticsWindowFromSampling`, FDD status filters, `confirm_min` on run, inspect title/stacking, series preview 10/20/50/100/500. SI storage; metric display default (imperial toggle deferred).

## RCx preset IDs

`ahu_motor_weekly`, `boiler_motor_weekly`, `chiller_motor_weekly`, `economizer_delta`, `economizer_mat_resid`, `economizer_temps_overlay`, `mech_cooling_oat_bins`, `bas_vs_web_oat` — loaders in `assets/js/rcx-presets.js`, **`index.html?tab=rcx`** + **`rcx-tab.js`**.

## FDD plots

**`index.html?tab=fdd`** + **`fdd-tab.js`** — rules list, status filter, `/api/fdd/run` with session `confirm_min`, `/api/fdd/plot` + inspect overlay via `chart-kit.js` / `fdd-api.js`.

## Related

- ADR: [`docs/architecture/adr-013-static-product-ui-central.md`](../../../docs/architecture/adr-013-static-product-ui-central.md)
- Archived React reference: [`archive/product-ui/react-spa-v4/`](../../../archive/product-ui/react-spa-v4/)
- [`openfdd-react-spa`](../openfdd-react-spa/SKILL.md) — historical SPA; new plot work lands here
