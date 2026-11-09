---
title: Changelog
nav_order: 14
---

# Changelog

## 5.0.5

- The deploy `doctor` labels failures correctly: `connectivity` (refused, DNS, unreachable, timeouts), `tls` and `auth` (real 401/403 only), fixing [#1549](https://github.com/bbartling/open-fdd/issues/1549). See [Troubleshooting](install.html#10-troubleshooting).
- The `fdd` hook fails loudly instead of reporting success with every output stale, with distinct reasons (`required roles missing`, `unit unusable`, `no input data in window`) and a run report of engine, window, newest input sample and counts; `doctor` gains an **fdd freshness** check; the `history` hook separates empty results from errors. Fixes [#1550](https://github.com/bbartling/open-fdd/issues/1550). See [FDD data access](fdd-data-access.html#checking-that-results-are-fresh).

## 5.0.4

- One-command installer (`install`, `doctor`, `uninstall`, `--remove-old`), a new [install guide](install.html) and [FDD data access](fdd-data-access.html) page. Fixes for ten deploy problems: Caddy/NF login mismatch and recovery, portal-key 401 message, the `/` redirect, dependency install on push, weather coordinates from the modeled site, `history` and on-request hooks skipped by a blanket `run`, static routes behind NF auth, orphan hook points, and self-signed HTTPS.

## open-fdd 4.5.2 (PyPI)

- Python 3.14 and 3.15 are now supported, with CI over 3.10-3.15. Python 3.10 gets an `enum.StrEnum` backport (`open_fdd/_compat.py`).

## 5.0.3 (app) / open-fdd 4.5.1 (PyPI)

- Weekly runtime on RCx: in-schedule vs after-hours bars and a schedule line read from NF schedules (holidays included); default Mon-Fri 07:00-17:00 in the site timezone; new 28-day range.
- Fault lanes use a per-timestamp fault timeline: a cleared fault reads 0, missing data stays a gap. Older results fall back to a dashed, approximate lane.
- Two sites with the same equip name (e.g. `AHU-1`) no longer share fault lanes or RDF subjects; site, equip and device subjects use NF uuids.
- Runtime and cooling-bin hours are integrated on a 5-minute grid, not the chart's display grid.
- VAV-1 gets occupancy from the site schedule when there is no `occ_mode` point.
- New read-only `analytics` hook and `open-fdd-nf analyze`: weekly runtime, mechanical cooling, economizer, fault timeline, role binding and "why is this RCx view missing". See [Python tools](python-tools.html).

## 5.0.2 (app) / open-fdd 4.5.0 (PyPI)

- New `open-fdd-nf` Python CLI and `open_fdd.nf` API: work with a local NF box or the Normal Online portal from Python. See [Python tools](python-tools.html).
- FDD results written to NF in batches (about 2 requests per run instead of one per result).
- Open-FDD Lite gets a strict CSP and the full edition's RDF export.
- The PyPI package now has its own version line (4.x), released by `open-fdd-v*` tags.

## 5.0.1

Patch release (correctness, data safety, hardening). Full list: [CHANGELOG.md](https://github.com/bbartling/open-fdd/blob/master/CHANGELOG.md).

- TimescaleDB retention only trims Open-FDD's own tables unless you explicitly allowlist others.
- One declared scale per command/position column; no more percent-vs-fraction guessing in SQL or pandas (#1541).
- Comfort fault-sample count follows the band settings (#1542).
- Site-scoped result ids; results carry `ok` / `fault` / `not-assessed` / `stale` status.
- Bounded history and SPARQL routes, safer UI retries, CSV formula neutralizing, Caddy access logs.

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
- The 4.x line is frozen at tag `v4.0.11-central`. See [Removed in 5.0](migration/nf-plugin/ARCHIVE_MAP.html).

Full list: [CHANGELOG.md](https://github.com/bbartling/open-fdd/blob/master/CHANGELOG.md).
