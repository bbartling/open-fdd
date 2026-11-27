---
name: add-rcx-chart
description: Add an RCx chart (view) to the Open-FDD NF app with the bottom fault lane and parity entry.
---
# Add an RCx chart

1. Pick the view module: `nf-app/static/rcx-overview.js`, `rcx-presets.js`, `fdd-plots.js` or `energy.js`.
2. Register it with `rcxView({ id, group, title, kinds, roles: { required, optional }, scope: "equip"|"site", render })`
   (`static/rcx.js`). Use role names that exist in `nf-app/static/fdd-catalog.json`; no site, equip or point names.
3. Fetch history with the shared helpers (NF resamples: `point/data ... window=Ns`). Work in SI; convert for display
   with `ofddUnits.fromSI` / `deltaFromSI`.
4. Faults: only through `rcxWithFaultLane(option, [{ name, data: [[ms, 0|1], ...] }])`. No markers, shading or extra series.
5. Add the view id to `nf-app/rcx-parity.json` (`presets` or the matching builder entry, and `fault_lanes` if it draws one).
6. Add or extend a test in `nf-app/tests/` (rcx-presets, rcx-overview or fdd-plots tests).
7. Overview cards load through `nf-app/static/lazy-cards.js`. A new panel fetches history only when it nears the
   viewport, and it stops when the user leaves the tab. Do not fetch history for an off-screen card.
8. The chart library is vendored ECharts (`nf-app/static/vendor/echarts.esm.min.js`). The UI stays plain JavaScript.
   Do not add React or Plotly.
9. Check it visually: `node nf-app/dev/mock-nf.mjs`, open `http://127.0.0.1:8765/api/v1/apps/static/open-fdd/`, Overview (the RCx dashboard; panels show only when the model has the equipment). `node scripts/nf/ui_acceptance.mjs` is the headless check.

Tests: `node --test nf-app/tests/*.test.mjs` (`parity.test.mjs` fails on a missing view or entry) and
`(cd nf-app && npm run typecheck)`.
