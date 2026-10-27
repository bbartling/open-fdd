# CSP style directives (#1130)

**Date:** 2026-10-27  
**Plugin:** OWASP ZAP 10055 (Content-Security-Policy: style-src unsafe-inline)

## Verdict

**Hardened in product nginx** — `style-src` and `style-src-elem` are `'self'` only.
`'unsafe-inline'` appears only on `style-src-attr` for Plotly inline `style="…"` attributes.

## Policy (openfdd-web `frontend/web/nginx.conf`)

Every `Content-Security-Policy` header includes:

- `style-src 'self'`
- `style-src-elem 'self'`
- `style-src-attr 'unsafe-inline'`

SPA, `index.html`, `/twins/` (Unity), and the server default block share this split.
`script-src` is unchanged (`'self' blob:`; Unity adds `'wasm-unsafe-eval'`).

## Plotly runtime styles

Plotly.js normally injects `<style>` nodes (global CSS, mode bar, maplibregl). That
violates `style-src-elem 'self'` without `'unsafe-inline'`.

Mitigation shipped with the SPA:

1. **`/plotly.css`** — same-origin static bundle generated from the vendored
   `plotly.min.js` (`node scripts/ci/export_plotly_css.mjs` after Plotly upgrades).
2. **`/plotly-csp-shim.js`** — loaded before `plotly.min.js`; routes Plotly's
   `CSSStyleSheet.insertRule` calls to the linked `/plotly.css` sheet and does not
   mount inline `<style>` nodes in the document.
3. **`displaylogo: false`** in `PlotlyHost` config (mode bar without Plotly logo SVG).

Plotly inline **attributes** still use `style-src-attr 'unsafe-inline'` only.

## Actions page

Component styles live in `ActionsPage.css` (no inline `<style>` block in React).

## CI guards

- `scripts/ci/check_csp_headers.sh` — parses every CSP in `nginx.conf`; fails if
  `'unsafe-inline'` appears outside `style-src-attr`.
- `frontend/web/e2e/csp-plotly.spec.ts` (T1130-1) — headless Chromium on Overview,
  RCx, Inspect, FDD Plots, and Actions; asserts zero `securitypolicyviolation`
  events and at least one `svg.main-svg` per Plotly host on chart pages.

## Other mitigations (unchanged)

- No remote script CDNs (`script-src 'self' blob:` only).
- Self-hosted fonts (`@fontsource`); no Google Fonts cross-origin stylesheet.
- HSTS on every `/api/*` proxy location when trusted `X-Forwarded-Proto: https`.
- `object-src 'none'`, `base-uri 'self'`, `frame-ancestors 'self'`.

## ZAP / disposition

Codex-owned passive ZAP may still list historical 10055 rows until the disposition
file is updated on a qualified tip. This document tracks the **product** header shape;
live scan evidence belongs in the private qualification report.
