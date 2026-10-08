# CSP `style-src 'unsafe-inline'` disposition (#1130)

**Date:** 2026-10-08  
**Tip context:** post Soft-OPEN 3.5.68 → 3.5.69 train  
**Plugin:** OWASP ZAP 10055 (Content Security Policy: style-src unsafe-inline)

## Verdict

**Stays dispositioned / open for product hardening** — not a silent "PASS".

## Why `'unsafe-inline'` remains in `style-src`

The React SPA serves Plotly charts (RCx Plots, Inspect, FDD Plots). Plotly applies
inline `style="…"` attributes on SVG/DOM nodes at render time. Those attributes
are not covered by `'unsafe-hashes'` (hashes apply to `<style>` / `style=` on
elements only when the exact hash is known a priori) and cannot be nonced because
Plotly generates them dynamically after the document CSP is fixed.

Removing `'unsafe-inline'` from `style-src` without a Plotly-compatible CSP
strategy breaks product charts. A train-sized nonce/hash migration was measured
as out of scope for the OOM architecture tip.

## Mitigations already in place

- No remote script CDNs (`script-src 'self' blob:` only).
- No Google Fonts cross-origin stylesheet (#1131 — `@fontsource` self-host).
- HSTS on every `/api/*` proxy location when trusted `X-Forwarded-Proto: https` (#1132).
- `object-src 'none'`, `base-uri 'self'`, `frame-ancestors 'self'`.

## Follow-up (not this tip)

- Evaluate Plotly config / CSS variables path that avoids inline styles, or
  a strict CSP report-only rollout with nonce for SPA-owned styles only.
- Keep #1130 open until ZAP 10055 is absent **or** this disposition is accepted
  with tip+live evidence that fonts/HSTS rows are clean.
