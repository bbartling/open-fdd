---
title: Changelog
nav_order: 14
---

# Changelog

## 5.0.0

Open-FDD is a Normal Framework app. This is a complete reset of the project.

**Added**

- `nf-app/`: the full app. UI tabs Overview, Charts, FDD, RCx, Points, Export (CSV), BACnet Server, and Model and RDF
  with a SPARQL panel. Hooks `fdd` (hourly, 77 SQL rules in SQLite-WASM or PGlite), `weather` and `sparql`.
- `lite/`: Open-FDD Lite (formerly "Bench Viz") for 1 GB boxes.
- RCx chart library with the bottom fault lane (`rcxWithFaultLane`) and `rcx-parity.json`.
- SI-only FDD math with an imperial / SI display toggle (`units.js`).
- RDF/Turtle export with Brick time-series references, SPARQL panel and hook.
- Optional Caddy front door (`deploy/nf-caddy`), CI for the app, ZAP, npm audit and gitleaks.
- This documentation site, rebuilt for 5.0, with a generated rule reference.

**Removed**

- All Rust, the 4.x central stack, GHCR images, Timescale ingest, the qualification harnesses, the old
  React/static UI, and the 4.x docs, runbooks and agent prompts.
- The 4.x line is frozen at tag `v4.0.11-central` (branch `release/4.x`). See [Removed in 5.0](migration/nf-plugin/ARCHIVE_MAP.html).

Full list: [CHANGELOG.md](https://github.com/bbartling/open-fdd/blob/master/CHANGELOG.md).
