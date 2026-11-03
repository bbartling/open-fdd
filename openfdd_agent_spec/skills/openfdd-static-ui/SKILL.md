---
name: openfdd-static-ui
description: >-
  Maintain the Open-FDD static product UI on central (`services/central/static/product`,
  served at `/app/`; default portal compose sets OPENFDD_STATIC_PRODUCT_UI=1 on central).
  Lean HTML pages, modular JS,
  vendored ECharts (no CDN), same-origin `/api` only, strict CSP without unsafe-eval.
---

# Open-FDD static product UI (central `/app/`)

## When to use

- Editing `services/central/static/product/` (HTML, CSS, JS) or `static_product.rs`
- RCx / FDD plot parity vs archived React SPA (`archive/product-ui/react-spa-v4`)
- Model tree + SPARQL (TTL-only on Model tab)
- CSV upload/export, hub admin read surfaces, synthetic M&V demo (Ops tab)
- Vendoring chart libraries under `assets/vendor/`

## Rules

1. **Same-origin `/api` only** — no CDN scripts, no `/api/v1`, no inline `style=""` or non-module scripts.
2. **CSP** — product CSP is `script-src 'self'` without `unsafe-inline` / `unsafe-eval`. Product JS must not call `eval` or `new Function`. ECharts ships full build; use canvas renderer paths exercised by RCx/FDD/Inspect charts only.
3. **Model tab** — tree and checks from **`GET /api/model/ttl`** and **`POST /api/model/sparql`** only. Do not call `/api/model/agent-context` on Model pages.
4. **Operational data** — historian points, package mapping, FDD session config, analytics, and FDD run/plot may use their existing `/api` routes from `assets/js/site-data.js`, `rcx-presets.js`, `fdd-api.js`.
5. **ECharts** — vendored under `assets/vendor/` with `.version` sidecar + `LICENSE.echarts.txt`. Pin latest stable; update sidecar when replacing files.
6. **Lean pages** — `index.html`, `tree.html`, `rcx.html`, `fdd.html` link CSS + module scripts only; logic lives in `assets/js/`.
7. **Parity** — match archived SPA behavior for Overview RCx presets, economizer gate (`ECONOMIZER_DT_MIN_C`), `analyticsWindowFromSampling`, FDD status filters, `confirm_min` on run, inspect title/stacking, series preview 10/20/50/100/500. SI storage; metric display default (imperial toggle deferred).
8. **Dynamic text** — use `textContent` / DOM APIs; never inject HTML strings from API responses.

## Tabs (index.html)

| Tab | Module | APIs |
| --- | --- | --- |
| Overview / Charts / Points | `app.js`, `charts.js` | health, mapping, historian |
| RCx | `rcx-tab.js`, `rcx-presets.js` | `/api/analytics/*` |
| FDD | `fdd-tab.js`, `fdd-api.js` | `/api/fdd/*`, session config |
| Schedules | `schedules-tab.js` | `/api/schedules/status`, ingest gaps, AFDD |
| **Ops** | `operations-tab.js` | CSV import/export, admin read, synthetic M&V |
| Model | `tree-view.js`, `ttl-model.js` | TTL + SPARQL |

## Ops tab (Wave E)

**`index.html?tab=ops`** + **`operations-tab.js`**

- **CSV card** — multipart `POST /api/csv/import/package`; list `GET /api/csv/import/package/buildings`; session-scoped site from header `?site=`; export via ephemeral `POST /api/jobs` + `POST /api/jobs/{id}/exports` (`kind: csv`) and authenticated download of `download_url`.
- **Admin card** — hub admin only (`GET /api/auth/me` → `hub_admin`); read-only tables from `/api/admin/users`, `/api/admin/tenants`, `/api/admin/historian-limits`.
- **Synthetic demo card** — deterministic seed in `mv-demo-seed.js`; `POST /api/analytics/mv` with ECharts scatter (no Plotly).

Styles: `assets/css/operations.css`.

## RCx preset IDs

`ahu_motor_weekly`, `boiler_motor_weekly`, `chiller_motor_weekly`, `economizer_delta`, `economizer_mat_resid`, `economizer_temps_overlay`, `mech_cooling_oat_bins`, `bas_vs_web_oat` — loaders in `assets/js/rcx-presets.js`, **`index.html?tab=rcx`** + **`rcx-tab.js`**.

## FDD plots

**`index.html?tab=fdd`** + **`fdd-tab.js`** — rules list, status filter, `/api/fdd/run` with session `confirm_min`, `/api/fdd/plot` + inspect overlay via `chart-kit.js` / `fdd-api.js`.

## CI smoke (no central image build)

Against a running central with static UI enabled:

```bash
OPENFDD_ADMIN_PASSWORD='…' ./scripts/ci/static_ui_smoke.sh
```

Optional: `OPENFDD_STATIC_UI_BASE=http://127.0.0.1:8080`.

Asset/policy gate: `./scripts/ci/static_product_guard.sh` (portal compose has no `openfdd-web`; rollback tree + `docker/compose.react.yml` required). Rust asset tests: `cargo test -p openfdd-central 'static_product::'`.

Real-stack browser CI uses the default portal compose (central + Timescale, static UI only): `static_ui_smoke.sh` then Playwright `e2e/static-product-csp.spec.ts` (`scripts/ci/real_stack_browser.sh`).

**Rollback:** `docker/compose.react.yml` + GHCR `openfdd-web` (same `OPENFDD_IMAGE_TAG` / `OPENFDD_WEB_IMAGE`). Set `OPENFDD_STATIC_PRODUCT_UI=0` on central when running the React container on `:3000`.

**Deferred (not Wave E):** ZAP AF and legacy React-only frontend soak — unchanged; do not mark passed.

## Related

- ADR: [`docs/architecture/adr-013-static-product-ui-central.md`](../../../docs/architecture/adr-013-static-product-ui-central.md)
- Handoff: [`docs/operations/GROK_CLOUD_STATIC_UI_HANDOFF.md`](../../../docs/operations/GROK_CLOUD_STATIC_UI_HANDOFF.md)
- Archived React reference: [`archive/product-ui/react-spa-v4/`](../../../archive/product-ui/react-spa-v4/)
- [`openfdd-react-spa`](../openfdd-react-spa/SKILL.md) — historical SPA; new plot work lands here
