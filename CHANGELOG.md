# Changelog

Two version lines: the NF app (`VERSION`, `nf-app/package.json`, tags `vX.Y.Z`) and the PyPI package
`open-fdd` (`pyproject.toml`, tags `open-fdd-vX.Y.Z`, which publish to PyPI).

## 5.0.4 — 2026-11-08

Deploy tooling and docs for installing Open-FDD on an existing NF site. All items below ship with the installer.

### Added

- **One-command installer** in `scripts/nf/hooks/nf_app_sync.py`: `install` (preflight, push, dependency install, verify), `doctor`, `uninstall`, and `--remove-old` (dry run unless `--yes`, driven by `app.json` `replaces`). New pages: [install guide](docs/install.md) (editions, credentials, reachability, upgrade, uninstall, a 10-bug troubleshooting table) and [FDD data access](docs/fdd-data-access.md) (where results live, how an API client reads status and timelines). New agent skill `install-upgrade-troubleshoot`.

### Fixed

1. **Caddy and NF logins diverging** had no recovery path: documented that both must share one user and password, a "which layer rejected me" table (`realm="restricted"` is Caddy, `nf-` is NF) and the recovery steps (test NF on loopback, `caddy hash-password` with the password on stdin plus a trailing newline, `caddy validate`, restart instead of `caddy reload` when `admin off`). `deploy/nf-caddy/README.md`.
2. **Portal API-key 401 on deploy** now says to use the console login.
3. **Caddy `/` redirect** is the `APP_ID` placeholder (`open-fdd` or `open-fdd-lite`), with the update procedure documented. Verified with `caddy adapt`.
4. **Push did not install npm dependencies** (`fdd` hook: `Cannot find package '@electric-sql/pglite'`): the installer installs them and restarts.
5. **Weather hook** reads latitude/longitude from the modeled Haystack site when NF's Sites API is empty.
6. **`history` hook** is skipped by a blanket `run` when Timescale is not configured.
7. **On-request hooks** (`sparql`, `analytics`) are no longer started by a blanket `run` without args.
8. **Open static routes vs NF console auth**: documented that opening a path in Caddy does not bypass NF's own login, and the recommended layout (Caddy owns the login). `deploy/nf-caddy/README.md`.
9. **Orphan hook points** after replacing an app: `--remove-old` lists them; documented the supported deletion (NF MCP `delete_points`, dry run first) and never reusing a point uuid on `POST /api/v1/bacnet/local`.
10. **Self-signed HTTPS front door**: `--ca-file` / `--pin-server-cert` for the deploy process, never global verification off.

## open-fdd 4.5.2 (PyPI) — 2026-11-07

- Python 3.14 and 3.15 are now supported (classifiers + a CI matrix over 3.10-3.15, `.github/workflows/python-matrix.yml`). Python 3.10 gets an `enum.StrEnum` backport (`open_fdd/_compat.py`); the app version is unchanged.

## 5.0.3 (app) / open-fdd 4.5.1 (PyPI) — 2026-11-07

### Added

- **Fault timeline.** The FDD hook now publishes a per-timestamp series for every fault rule that has one (68 of 77):
  a second result point per (equip, rule), marker `fault_timeline` (no `fdd`/`fault` marker, so the FDD table does not list
  it), with the rule's own confirmed flag at each assessed history timestamp: 1 = confirmed fault, 0 = ok, no sample = not
  assessed (never written as 0). Append-only (watermark attribute `fddTimelineThrough`), no duplicates. The SQL packs carry a
  `timeline_sql` per rule (`null` + `timeline_reason` for the 9 rules with no per-row flag: ratio, count and window-statistic
  rules); PGlite and SQLite are tested for parity, and confirmed seconds add up to `fault_hours`.
- **Read-only agent analytics tools**: on-request hook `analytics` (`nf-app/hooks/analytics.js`, `args.tool`):
  `analyze_ahu_weekly_runtime`, `analyze_mechanical_cooling`, `analyze_economizer`, `get_fdd_fault_timeline`,
  `resolve_equipment_roles`, `explain_missing_rcx_view`. They reuse the dashboard math (fine grid, schedule-aware), key every
  row by `equipUuid` and cannot write (the hook's HTTP client is a GET / read-POST allow-list). CLI:
  `open-fdd-nf analyze TOOL [--site --equip --rule --days --json]` (StartHook is sent once, never retried). Docs: `docs/python-tools.md`.
- Result and timeline points carry `equipUuid`; rules that use `occ_mode` carry `fddOccSource` (`point` | `schedule` | `default`).

### Fixed

- **Fault lane showed rolling `fault_pct > 0` as "in fault" and missing data as ok.** `rcxFaultData` now reads the timeline:
  a fault that cleared reads 0 even while the rolling 24 h percentage is still above 0, and unknown stays a gap (null).
  Without a timeline point (hook older than 5.0.3, or a rule without one) it falls back to the old `fault_pct` series, labelled
  approximate (dashed lane). The existing `fault_pct` point, uuid and meaning are unchanged: no migration is needed; the
  timeline fills in from the first 5.0.3 run (the whole trailing window, 24 h by default).
- **Two sites that both have an equip `AHU-1` shared one result point / fault lane.** `rcxResultPoint` / `rcxFaultData` now
  take the equip (record or `OfddEquip`) and match by NF equip uuid, else siteRef + equipRef; a bare equip id string is still
  accepted but cannot tell sites apart.
- **VAV-1 (and every rule with an optional `occ_mode`) scored occupied comfort limits around the clock without an `occ_mode`
  point.** The hook now synthesizes `occ_mode` from the site's NF schedule (holidays included) or the 4.x default calendar
  (Mon-Fri 07:00-17:00, site timezone) before the SQL runs. VAV-2 still requires a real `occ_mode` point.
- **RDF subjects collided across sites.** `modelToTurtle` (app and Lite) now uses the NF record uuid for site, equip and
  device subjects (points already did), else a site-prefixed id (`local:<siteRef>_<id>`); `siteRef` / `equipRef` / `deviceRef`
  point at those subjects. Anything that queried `local:<haystack id>` directly must switch to joining on `rdfs:label` and
  `phIoT:siteRef`; the SPARQL example `equips-kinds` now has a `site` column and groups per equip.
- `mergeFaultLanes` turned null (not assessed) into 0 when OR-ing several equips.

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
