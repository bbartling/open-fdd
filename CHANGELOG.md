# Changelog

Two version lines: the NF app (`VERSION`, `nf-app/package.json`, tags `vX.Y.Z`) and the PyPI package
`open-fdd` (`pyproject.toml`, tags `open-fdd-vX.Y.Z`, which publish to PyPI).

## 5.0.11 - 2026-11-10

- Split large history requests so Faults lanes can render through NF's front door. Show a visible history error in the panel and retain the unit scales and mixed-history cutover (#1571, #1566).
- Publish sensor results only for roles the sweep assesses. Persist null fault hours for an assessable sensor with no coverage and keep numeric zero for an assessed sensor without faults (#1572).
- Check the Timescale schema before an install and in doctor. Restore the previous app if post-install verification fails (#1570).

See the [5.0.11 NF migration note](docs/operations/nf/migrate-5.0.11.md).

## 5.0.10 - 2026-11-09

- Accept explicit NF and BACnet flow, pressure, temperature, and percent aliases. The hook reports skipped units and doctor warns when they occur (#1564).
- Write Open-FDD result attributes explicitly so NF's merge behavior clears obsolete values on the next run (#1563).
- Evaluate all five sensor sweeps by point UUID, including multiple sensors with the same role. Sensor points store fault and coverage hours, and the equipment summary retains the highest sensor fault hours. Timescale schema v3 adds `sensor_ref` and `role` and keys results by run, equipment, rule, and sensor (#1565).
- Show per-sensor fault results and timelines. Display hours and percentages on separate scales and trim summary history at the current output boundary (#1566).

See the [5.0.10 NF migration note](docs/operations/nf/migrate-5.0.10.md) for point identity, the summary JSON shape, and the Timescale upgrade.

## 5.0.9 - 2026-11-09

- Documented the installer file-presence checks and tested the production HTTP client against NF's empty gRPC 500 response. Known files still fail on read errors (#1557, #1558).
- Shared StartHook argument handling across the history, analytics and SPARQL hooks. Installer verification preserves the run outcome when a Windows console cannot encode a hook event (#1559, #1560).
- Generated the standalone scratch DDL and NF pack schema from one typed SI input contract (#1547).
- Sensor sweeps now attribute fault hours to individual roles, count extended reporting gaps and use elapsed-time windows. Existing equipment results expose the worst sensor's hours and retain every assessed role's score (#1555).
- Bounded weather lookups and allowed time for fetch retries and writes in both editions. Redacted Timescale driver diagnostics that could expose short passwords.

## 5.0.8 - 2026-11-09

Hand-edit guard on NF consoles that answer a missing app-file GET with HTTP 500:

1. **Missing-file detection:** A path absent from the installed app's `files` list (from `GET /api/v1/apps`) is treated as not on the box. When a GET is still made, NF's observed not-found signature (HTTP 500, `Content-Type: application/grpc`, empty body) is treated as missing **only** for paths that are new relative to the box (not in that file list, or not in the last push manifest). Every other HTTP 500 still aborts the push. Response bodies are still never copied into error messages (#1554).
2. Unblocks installing releases that add new hook files (for example `/hooks/lib/paging.js` and `/hooks/lib/settings.js`) onto a 5.0.5 box whose console returns 500 instead of 404 for paths that are not there yet.
3. **History StartHook args:** `history.js` coerces NF's string→string StartHook map so a JSON-array `uuids` string and optional `windowHours` become the array / `from`+`to` that `historyRoute` expects (live console verification).
4. **Windows console:** `nf_app_sync.py` report_run no longer crashes when a hook event contains non-cp1252 Unicode.

## 5.0.7 - 2026-11-09

Follow-up to 5.0.6 CodeRabbit review:

1. **Hand-edit guard:** HTTP 500 on a remote file read no longer looks like a missing file; only 404 means missing. A read error on `/static/version.json` also propagates (no silent fall-back to the repo baseline). Non-auth HTTP error messages omit the response body so proxy/error pages cannot leak credentials.
2. **Credential redaction:** `redact` replaces the known `connectionString` before userinfo masking. Bare passwords of length ≥ 3 are replaced; shorter ones are not (avoids mangling diagnostics such as `connection refused`), while short passwords inside a connection string are still covered by the connectionString replace.
3. **Weather model lookup:** later-page and first-page non-404 point/query failures propagate (not an empty layer); the paginated model-site lookup uses a 45s deadline; the whole-run deadline and NF `invokeTimeout` are 120s so lookup + Open-Meteo fetch + writes still fit.
4. **Doctor Sites paging:** the Sites adapter forwards `pageToken` as well as `pageOffset`.


## 5.0.6 — 2026-11-09 (app) / open-fdd 4.5.3 (PyPI)

Patch for a live site where `fdd`, `history` and `weather` all failed every run after installing 5.0.5 ([#1550](https://github.com/bbartling/open-fdd/issues/1550)).

### Fixed

1. **Point-query paging** (the real cause of the frozen `fdd` results). NF `POST /api/v1/point/query` returns `totalCount` and **no next-page token**; it pages with `pageOffset`. Every reader followed only a token, so it read the first 500 records. Once results published by the `fdd` hook grew the model layer past 500 records the SITE fell off page 1, every run saw `0 equips` and wrote nothing. One pager per runtime now follows a token when there is one, else `pageOffset` until `totalCount` (or an empty / short page), and ends loudly on a repeated page, a short read or a hard cap (200000 records / 1000 pages); it never returns a truncated list. Hooks (`fdd`, `analytics`, `sparql`, `weather`: `nf-app/hooks/lib/paging.js`; the Lite weather hook inline), the static pages (`static/nf.js` `pageAll`, full and Lite; `schedule.js` gets a cap), `nf_app_sync.py` (`doctor` freshness and weather checks, the orphan scan), `scripts/nf/tools`, and `open_fdd.nf.NFClient.query_all` / `sites` (`page_all`). The dev mock NF now pages like NF.
2. **Hooks could not read the Timescale connection or the site coordinates.** NF stores app **options**, not a hook-definition `config`, and passes the option values to the hook as `ctx.config` (scalars only). `fdd`, `history` and `weather` now read them that way: `timescale` is a JSON string (or a `postgres://` URL), `windowHours` / `latitude` / `longitude` may be strings, blank options are "not set". Weather coordinates: the `latitude` / `longitude` options, then NF Sites, then the modeled site. A missing or unusable setting fails with one message naming where to set it (`Timescale connection settings not found: set the app option "timescale" ...`); the password and URL credentials never reach a log or error. `docs/install.md` documents the real mechanism (the old hook-config + `OPENFDD_PG_PASSWORD` instructions did not work on NF 3.10.x).
3. **"0 equipment" was reported as "required roles missing".** The `fdd` hook now fails with its own reason: `model empty: 0 equipment resolved from the model layer (...; N model records read of totalCount M)`, `model incomplete: ... although N published results exist`, or `model incomplete: N equipment but 0 points loaded`.
4. **`install` silently overwrote files edited on the box.** Every push records a manifest (sha256 per file) in `static/version.json`. The next `push` / `install` compares the box with it first and stops (exit 4, nothing written) when a file was hand-edited, listing the files; `--save-remote DIR` downloads the edited copies, `--force` overwrites. An older install without a manifest is compared with its installed commit (else the repo copy) with a warning. `doctor` lists hand-edited files (read-only). Text files are now uploaded with LF line endings whatever `core.autocrlf` is.
5. **`doctor` said `timescale: configured` when the hooks could not read it.** It now parses the `timescale` option the way the hooks do and fails on an unreadable value (never printing it); `weather coords` also reads the app options.

## 5.0.5 — 2026-11-09

Diagnostics patch: the deploy `doctor` names what actually failed, and the `fdd` hook can no longer report success while writing nothing.

### Fixed

1. **`doctor` called a refused connection an auth failure** ([#1549](https://github.com/bbartling/open-fdd/issues/1549)). `nf_app_sync.py` now classifies failures as `connectivity` (refused, DNS, unreachable, connect or read timeout: "credentials were not validated", with the hint to use the front-door URL, not NF's own loopback port), `tls` (certificate trust or host name: use `--ca-file` / `--pin-server-cert`, never a bypass) and `auth` (only real HTTP 401 / 403, distinguished, realm guidance kept). Messages carry scheme, host, port and path only; every failure exits non-zero and stays read-only. See [Troubleshooting](docs/install.md#10-troubleshooting).
2. **`fdd` hook reported `STATE_SUCCESS` with every output stale** ([#1550](https://github.com/bbartling/open-fdd/issues/1550)). A run with eligible equips but no freshly assessed result now fails (NF records a non-success state). Stale reasons are distinct: `required roles missing`, `unit unusable (role ...)`, `no input data in window (newest sample at <ISO>)`. The run log and summary always carry the engine, data window, newest input sample (engine source and NF latest value) and eligible / evaluated / written / skipped / stale counts with reasons.
3. **`history` hook** returns `ok: true` with `reason` and `newest_source_ts` for an empty range, and `ok: false` with the error for a connection or query failure. See [FDD data access](docs/fdd-data-access.md#checking-that-results-are-fresh).

### Added

- `doctor` check **fdd freshness**: FAIL when computed FDD points are older than 2x the fdd schedule while raw history is fresh.

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
