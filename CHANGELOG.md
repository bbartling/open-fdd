# Changelog

Two version lines: the NF app (`VERSION`, `nf-app/package.json`, tags `vX.Y.Z`) and the PyPI package
`open-fdd` (`pyproject.toml`, tags `open-fdd-vX.Y.Z`, which publish to PyPI).

## 5.0.2 (app) / open-fdd 4.5.0 (PyPI) — 2026-11-07

### Added

- **`open_fdd.nf`** and the **`open-fdd-nf`** CLI (`info`, `model`, `pull`, `rules`, `report`): AI agents and engineers
  work directly against a local NF box or the Normal Online portal — load the Haystack model, bind rule roles,
  pull SI history as pandas DataFrames and run the pandas reference rules. Docs: `docs/python-tools.md`.
- `open-fdd-report` reads from NF (`--nf`) or the app's CSV export (`--csv`).
- FDD hook writes results in batches (NF `AddData` + one `UpdatePoints` per run): 10 equips × 20 rules goes from
  ~215 requests to 2. Retries only on 429/503; partial failures counted per point.
- README: Open-FDD Grok bot skills badge and button.

### Changed

- Open-FDD Lite: strict CSP on every page (no inline styles/handlers); RDF export matches the full edition
  (Brick time-series references, defined terms).
- PyPI package versioned separately (4.5.0) and published only by `open-fdd-v*` tags; app tags no longer trigger PyPI.
- `open_fdd.__version__` is the package version; `open-fdd-version` also shows the app version.
- README rewritten shorter.

### Removed

- Readers for the retired central API (`OpenFddApiSource`, central SPARQL consumer bundle), the 4.x `vibe19`
  compatibility shims, and the dead `--dump` / `--package` report inputs.

## 5.0.1 — 2026-11-07

Patch release from an external review (Codex / ChatGPT) and open issues. No new features; correctness, data safety and hardening.

### Fixed

- **TimescaleDB retention could delete NF or other apps' history (P1).** The size cap (default 100 GB) now only drops chunks of
  Open-FDD's own tables (`openfdd.*`); other hypertables only via an explicit, validated `retention_allowlist` (fails closed).
  Chunk budget, no-progress exit, `retention_preview()` dry run and a `retention_log`. Upgrading re-scopes an existing job in place.
- **Percent vs fraction (#1541).** Every command/position column has one declared scale (`sql/fdd/role_scales.json`): the hook
  converts by declared unit, the SQL rules and the pandas oracle no longer guess by magnitude; unitless command points are skipped,
  not guessed. A 1 % fan command is no longer read as full speed. Same rules on SQLite, PGlite and TimescaleDB.
- **Comfort fault-sample count used fixed bounds (#1542).** `fault_samples` now uses `ZONE_T_LO` / `ZONE_T_HI` like hours and pct.
- **Result identity is site-scoped.** Two sites with the same equipment id no longer share (and overwrite) a result point.
  5.0.0 result points are not reused; operators can delete them later.
- **Unknown is not healthy.** Fault rules with no coverage are `not-assessed` (no value written), results that could not be
  refreshed become `stale`, every result carries `fddStatus` / `fddReason` / `fddLastRun`, and a run with rule errors fails visibly.
- History route bounded before querying (span, bucket, UUIDs, max points, 20 s statement timeout, coverage/truncation flags).
  Explicitly selecting the Timescale engine without settings fails instead of silently falling back.
- UI client never auto-retries non-idempotent POSTs (e.g. "Run FDD now"); CSV export neutralizes spreadsheet formulas.
- SPARQL: read-only query policy (no UPDATE / SERVICE), single execution, model size limit, browser queries in a Web Worker
  with a 20 s kill. `nf_app_sync.py run` waits up to the hook's timeout, reports "still running" (exit 3), supports `--resume`.
- #1537 / #1538 (4.x analytics SQL): resolved by the 5.0 binding — regression tests in `nf-app/tests/binding-issues.test.mjs`.

### Changed

- Caddy front door: structured access log with secrets redacted; security posture documented (plain HTTP = trusted LAN/lab,
  HTTPS = production; the open read routes are an explicit choice). Clerk login script pinned to an exact version and the
  CSP exception documented truthfully.
- Destructive Timescale test fixture only runs in a throwaway, marked database it creates itself; CI runs the Timescale suite
  against a real TimescaleDB service and fails on skips.
- Installed version recorded as the NF app setting `version` on every deploy (also shown in the app header).
- `release/4.x` branch removed (4.x stays reachable at tag `v4.0.11-central`).

## 5.0.0 — 2026-11-06

Open-FDD is now a **Normal Framework (NF) app**: a complete reset. FDD and analytics math run in SI only; the UI
shows imperial or SI through a toggle.

### Added

- **`nf-app/`**, the full edition (app id `open-fdd`): UI tabs Overview, Charts, FDD, RCx, Points, Export (CSV),
  BACnet Server, and Model and RDF with a SPARQL panel. Hooks: `fdd` (hourly, 77 SQL rules in SQLite-WASM or PGlite),
  `weather` and `sparql` (`POST /api/v1/apps/open-fdd/hooks/sparql`, `args.query`, `args.format`).
- **`lite/`**, Open-FDD Lite (app id `open-fdd-lite`, formerly "Bench Viz") for 1 GB boxes: no FDD engine, no npm dependencies.
- RCx chart library (60 views) with faults always drawn as the bottom 0/1 lane (`rcxWithFaultLane`) and `rcx-parity.json`.
- CSV export for Excel; imperial/SI display toggle (`units.js`); RDF/Turtle export with Brick time-series references.
- Type-checked JavaScript (JSDoc + `tsc`), optional Caddy front door (`deploy/nf-caddy`), `scripts/nf/hooks/nf_app_sync.py` deploy tool.
- CI: NF app, pandas == SQL parity, security (ZAP against the mock NF, npm audit, gitleaks), docs, PyPI publish.
- Documentation site rebuilt for 5.0 with a generated rule reference (`scripts/nf/gen_rule_docs.py`), and a compact agent spec (`openfdd_agent_spec/`).

### Removed

- All Rust, the 4.x central stack, GHCR images, Timescale ingest, the qualification harnesses, the old React/static UI,
  and all 4.x docs, runbooks and agent prompts. See [docs](docs/migration/nf-plugin/ARCHIVE_MAP.md).

## 4.x and earlier

4.x history: see tag `v4.0.11-central`.
