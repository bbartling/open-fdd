# Changelog

Two version lines: the NF app (`VERSION`, `nf-app/package.json`, tags `vX.Y.Z`) and the PyPI package
`open-fdd` (`pyproject.toml`, tags `open-fdd-vX.Y.Z`, which publish to PyPI).

## Unreleased

(nothing yet)

## 5.0.16 — 2026-11-12 (app) / open-fdd 4.5.7 (PyPI)
One small shared core schema, the 5.0.16 UI pass, optional weather and pluggable outputs, NF-native install bundles, and
parity hardening. Parity at the 8 equipment x 7 days stress size: compared=71 matched=47 known-divergent=24 unexpected=0, every
known difference inside its pinned delta band; 4 x 3 gives 50/21 (TRIM-4 now matches there); both pinned in
`tests/parity/baseline.json`. FDD outputs change in two places, called out below (#1587 site time zone, #1588 TRIM-3/TRIM-4).

- **FDD outputs change for sites that set the `timezone` app option (#1587).** The `fdd` hook's occupancy schedule (the VAV-1 `occ_mode` synthesis) and the `analytics` hook's weekly runtime now resolve the site time zone in the dashboard's order: model site `tz`/`timezone`, then the `timezone` app option, then NF Sites, then the host zone, then UTC. Before, the hook used the model `tz` or the host zone, which is UTC on real NF, so a site that had only set the option (or NF Sites) was evaluated in UTC and its occupied hours were shifted by the UTC offset. After upgrading, such a site's VAV-1 fault timeline and `fddOccSource` results move to site-local 07:00-17:00 (and shift an hour across DST); sites with a model `tz` are unchanged. The run summary reports `timezones: {site: {zone, source, fallback}}` and the log names the source.
- **Weather is optional, and outputs are pluggable (#1552).** App option `weather: false` (alias `weatherEnabled`) switches the weather hook off: no outbound request and no NF call, the hook returns `{skipped: true, reason: "weather disabled"}`, and `doctor` reports "weather disabled" instead of a failure. With it off (or when no weather point is bound) the `fdd` hook feeds the equipment's own outside-air sensor to the rules that read `web_oa_t` ("web first, else local", as RCx already did); a rule with no outside-air temperature skips with a reason, and OAT-METEO is skipped. Stale weather points are ignored while it is off (FDD, RCx, degree days). The BACnet mirror is now one exporter of a list (`exporters` option, interface in `docs/install.md`): hook variables are always written, and `bacnet-av` runs by default only when NF's BACnet server answers `GET /api/v1/bacnet/configuration`. **Behaviour change:** a site with no BACnet server no longer gets a failed weather run; the exporter is skipped and the summary says why.
- **NF-native install bundles (#1567).** `scripts/nf/build_app_dist.py` builds, per edition, the tree NF's own git-URL install reads (`app.json` as the CreateApplication request, `hooks-update/*.json`, hooks, static, `package.json`) from the same manifest `nf_app_sync.py` pushes; CI attaches `open-fdd-<version>.zip` and `open-fdd-lite-<version>.zip` (+ `SHA256SUMS`) to each release. The four install methods, the non-SSH / IT path and what still needs a live NF site are in the Normal Framework docs page; AGENTS.md now states that SSH is optional.

- **Breaking (schema):** Timescale schema version 4. `sql/fdd/schema/core.sql` defines `fdd.point`, `fdd.rule_result` and `fdd.rule_config`; the NF app installs it and downstream applications vendor it byte for byte (`open_fdd/data/core.sql` in the wheel, `core.catalog.json`, `scripts/nf/build_core_schema.py --check`). `openfdd.fdd_results` and `openfdd.retention_log` are copied (row-count guarded) and dropped on upgrade; see `docs/upgrade-5x.md` for rollback.
- The `fdd` hook mirrors the bound points into `fdd.point` and loads history from the view `fdd.input_sample` (SI by `si_scale` / `si_offset`; was a per-query affine in JS). Results are upserted into `fdd.rule_result` on a primary key that now includes the window and a rule hash. The schema probe reports `core_ok`.
- Input contract version 3: `sources` declares the `fdd.input_sample` signature every application exposes. `sql/fdd/tuning_storage.sql` is a pointer.
- Parity: `Dataset.to_core_rows()`, `to_imperial(ds)`, `TimescaleAdapter`, `stress.py --engines ...,timescale`, `tests/parity/baseline.json`.

- **TRIM-3 / TRIM-4 aligned with the SQL contract (#1588).** pandas reads the contract roles `hot-water-reset-request-sum` / `chilled-water-reset-request-sum` and faults at request sum <= `request_lo` like SQL. **Behaviour change (SQL):** an absent request sum is no longer treated as zero, so equipment with no request-sum point gets no TRIM-3/TRIM-4 result instead of a fault. The remaining stress difference is the pandas 600 s hydronic-proof startup holdoff (TRIM-4 scope `all` -> `stress_only`).
- **Pinned known-difference deltas (#1590).** Every stress known difference carries its expected fault-hour delta and tolerance per canonical dataset (`expected` in `open_fdd/data/parity_known_differences.json`, table in `docs/rules/parity.md`); `stress.py` fails when a delta leaves its band. The policy rejects ERROR status and non-finite fault hours; adapter conformance requires a finite `fault_hours`.
- **One unit table.** `open_fdd/data/unit_factors.json` (the NF ingest factors, e.g. 249.0889 Pa/inH2O, 0.4719474 L/s per cfm) feeds `open_fdd.units.convert`, `open_fdd.nf.units`, the imperial parity helper and the JS `units.js` (`scripts/nf/build_unit_factors.py --check` in CI); the fourth-digit mismatch found in the first 5.0.16 pass is gone and `to_imperial` drops its `ingest=` argument. The parity generator is version 2 (hashes in `parity_hashes.json`).
- Timescale parity runner: one rule run over all equipment (the PGlite batching), text rule outputs kept in `rule_result.diagnostics.outputs`.
- **Sweep tuning phase 2 (#1589, Full edition).** Persisted SI role-limit overrides for the five sensor sweeps: one revision per save in `fdd.rule_config` (`rule_id` `SV-LIMITS`, `scope_key` `site` or `equip:<id>`, append-only, one active per scope), precedence shipped file, then site, then equipment. New on-request hook `tuning` (actions get / preview / save / reset / rollback / history) validates the merged set exactly like `validate_role_limits` before it stores anything; new Full-edition **Tuning** tab (plain JS + ECharts band chart) edits in display units (absolute temperature, temperature difference and rate are separate conversions; inH2O, cfm, gpm from `unit_factors.json`) and shows each value's SI number, source and consuming rule. The `fdd` hook (Timescale engine) re-renders the sweeps per equipment from the pack's new `role_limit_templates` (byte-identical to the pack SQL with the shipped limits, checked by `build_sql_pack.py` and a JS test) and records `config_revision`, `config_hash`, the rendered `rule_hash` and `effective_parameters` on every sweep row; an override that no longer validates is skipped loudly. Python: `open_fdd.rules.role_limit_overrides` (merge, conversions, storage helpers), `render_rule.render_template` / `fill_template`. No editor in Lite. No result changes until a revision is saved.
- Review follow-ups: the pager refuses overlapping offset pages and enforces `maxRecords`; the weather BACnet mirror never overwrites an AV it does not own; the optional zone reads on the dashboard are bounded (5 s) and run together; a lone NF Sites record is not lent to an unmatched site of a multi-site model; `install --skip-hooks` never replaces an older schema hook; the schema hook redacts the host, user and database of a `postgres://` option from driver errors.

## 5.0.15 — 2026-11-11 (app) / open-fdd 4.5.6 (PyPI)

Tidy-up; FDD results are unchanged (parity: compared=71 matched=47 known-divergent=24 unexpected=0).

- **Breaking (contract):** SQL input contract version 2 drops the scratch tables `authorized_series` and `equipment`. 0 of 77 rules read them; the hooks no longer fill them (two fewer TEMP tables and inserts per run). Rule SQL and packs are otherwise byte-identical. An integrator that built views for those two relations can delete them.
- One shared source (`shared/`) for the code both editions had hand-copied: `nf.js`, `model.js`, `theme-init.js`, `tree.css`, `version.js`, the weather hook, `settings.js`, the pager and `shapes.d.ts`. `python scripts/nf/sync_shared.py` writes the copies into `nf-app/` and `lite/`; `--check` (and a pytest) fails when one drifts.
- UI shell shared by Full and Lite (`shared/static/app-core.js`, `charts.js`, `theme.js`, `chart-page.js`, `tree.js`, `base.css`): the same top bar, tab router, Overview, Charts, Points, BACnet Server and Model & RDF in both editions; each edition's `app.js` only adds its own tabs. Lite now uses the same theme layer and chart catalog as Full (live light/dark switch, no page reload).
- The top bar shows only the site; every tab that needs an equip has its own equip picker, and weather is its own **Weather** entry (weather points are no longer listed as an equip's sensors).
- Every history view now opens on the last 7 days (was All). The "Weather vs outside air" chart is removed from Charts; the hour-of-day heat map has a sensor dropdown; "Other signals" plots every numeric signal with one y-axis per unit and a bottom lane for on/off points.
- One pager: `shared/paging.js` (CommonJS in the hooks, `OfddPaging` in the pages; pages load `paging.js` before `nf.js`). It replaces four inline copies.
- One weather hook source for both editions. Hook ids and entry points are unchanged. The BACnet mirror is on by default in both editions (the default is built into the hook, since NF drops hook-level config; Full's manifest now asks for the `normalgw.bacnet.v1/v2.readwrite` scopes it needs), and the app option `bacnetMirror: false` turns it off. Lite also gains the `latitude`/`longitude` option override.
- `sql/fdd/tuning_storage.sql` is documented as the tuning storage contract (no Open-FDD component reads or writes it; kept at its path for integrators). `openfdd.fdd_results` is documented as the durable integration output.
- Docs: "Hooks and data surface" tables (`nf-app/README.md`, `openfdd_agent_spec/ARCHITECTURE.md`).
- Removed the stray `nf-app/timescale/integration.diff`; moved the test-only `synthetic_dataset.js` from `nf-app/hooks/lib/` to `nf-app/tests/fixtures/`.

## 5.0.14 — 2026-11-11 (app) / open-fdd 4.5.5 (PyPI)

- Parity harness in the PyPI package (`open_fdd.parity`): `generate` (basic profile bit-identical to the JS generator; `edge` profile with null runs, gaps, jitter, duplicate and out-of-order rows, a DST week, planted faults), `reference`, `Policy`/`compare`, adapter interface, imperial-ingest helper. Known differences ship as data; `stress.py --profile` (#1591).
- Edge profile: 6 input-handling differences documented and pinned with reasons (FC8, FC9, VAV-7, VAV-1, FCU-VALVE-PASS-CLG, WX-1).
- Shared plot spec v1 (`open_fdd.plot_spec`, `nf-app/static/plot-spec.js`), model-only series selection. Canonical `rcx_presets.json` registry (42 presets, aliases, new `ahu-cooling-valves`/`ahu-heating-valves`), `palette.json`, `units.json`, `plot_spec.schema.json`; `docs/plot-spec.md`. No UI change yet.
- Installer bootstraps the NF-side schema probe on apps that predate it, so an upgrade from 5.0.12 or earlier needs no psql or DB route; `install --dry-run`; doctor WARN when the probe isn't installed yet (#1593, #1585).
- Doctor explains an HTML answer from the console URL as a likely front-door URL (#1594).

## 5.0.13 — 2026-11-11 (app) / open-fdd 4.5.4 (PyPI)

- Resolve the site timezone from the modeled site, a new validated `timezone` app option, or the NF Sites API before the browser zone and UTC in Full and Lite; show `UTC (fallback)` when nothing is set and make `doctor` warn (#1584).
- Read the Timescale schema version through a read-only NF-side `schema` hook so `doctor` and `install` need neither a database route nor `psql`; the `NF_TIMESCALE_PREFLIGHT_DSN` path remains the fallback for older releases (#1585).
- Count a stale result once in `doctor`; fault-timeline companions are reported separately (#1586).
- Prove with a mock NF that silently drops out-of-retention AddData samples that a supported run (`windowHours` within retention) never loses a timeline retry, and pin the unsupported limit (#1574).
- Parity: `tests/parity/stress.py` exits non-zero on an unlisted pandas-vs-SQL divergence or when fewer rules are compared than have a pandas twin, and prints a one-line summary (#1582).
- Parity: TRIM-3 and VAV-REHEAT stress differences root-caused and pinned with reasons: startup holdoff, and the request-sum role name, threshold and gate (#1582).
- Sensor sweeps: one typed SI role-limit source (`open_fdd/data/sensor_sweep_limits.json`) feeds the SQL renderer and pandas sweeps; defaults unchanged, pack byte-identical (#1581).
- Sensor sweeps: new plant roles (CHW flow, CHW differential pressure, condenser-water supply/return temperature, chiller kW) with conservative SI range limits (#1581).
- Docs: removed stale references to retired 4.x SQL engines.

## 5.0.12 - 2026-11-10

- Open chart history on All and add 1 h, 24 h, 1 week, and custom ranges (#1577).
- Collapse empty stale Faults lanes and keep assessed-zero results visible (#1578).
- Round coverage and fault duration labels for display (#1579).
- Explain how to preflight a loopback-published Timescale database from a separate deploy machine (#1576).
- Publish concise SQL, pandas, API, and NF install guides and remove internal episode notes from GitHub Pages (#1580).
- Run native SI pandas and SQL parity stress before the mock NF ZAP scan on every patch.

See the [NF install and upgrade guide](docs/install.md).

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
