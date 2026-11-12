# Open-FDD NF app (`nf-app/`)

Open-FDD as **one Normal Framework (NF) application**, id `open-fdd`
([ADR-014](../docs/architecture/adr-014-open-fdd-as-nf-plugin.md)). NF does the field bus, the point model
(Haystack tags), history, auth, remote access (Normal Online) and config backups; this app adds the Open-FDD UI,
the FDD hook and the weather hook. Install: [docs/install.md](../docs/install.md).
What it uses from NF and why: [NF_FEATURES.md](../docs/migration/nf-plugin/NF_FEATURES.md).

## Layout

| Path | What | Run by |
|---|---|---|
| `app.json` | Manifest: application, file map, hook definitions | `scripts/nf/hooks/nf_app_sync.py` / NF MCP |
| `static/index.html` | UI tabs: Overview · Charts · FDD · RCx · Points · BACnet Server · Export · Model & RDF (+ `chart.html`, `tree.html`) | NF at `/api/v1/apps/static/open-fdd/` |
| `static/nf.js`, `static/paging.js` | **Shared with Lite** (`shared/`, copied by `scripts/nf/sync_shared.py`). NF access: login (LAN or Normal Online/Clerk), `api()`, live push stream | browser |
| `static/model.js` | **Shared with Lite.** Haystack model loader + RDF/Turtle export with time-series refs | browser + FDD hook |
| `static/fdd.js`, `fdd-catalog.json` | Rule catalog + role binding (NF class, else Haystack markers); rule title + `rule` badge helpers, the FDD tab's heat-map row selection | browser + FDD hook |
| `static/rcx.js` | RCx view registry (`tab` rcx/fdd, `fleet`, `headline`), binding, VAV→AHU feed (`airRef`) + the "AHU on" filter, KPI tiles, shared math, **the fault lane** (`rcxWithFaultLane`) | browser |
| `static/fdd-plots.js` | Per-rule plot (signals + bool fault lane) and the FDD sensor validation chart (worst sensor, four SV lanes: Range, Rate, Spike, Stale) | browser |
| `static/rcx-overview.js` | AHU run hours per day, weekly runtimes, mechanical cooling, economizer, BAS vs web OAT (an FDD-tab chart) | browser |
| `static/rcx-presets.js` | The RCx presets: zones (10th–90th percentile band, comfort), rogue VAVs, VAV positions / reheat temps, scatter plots | browser |
| `static/export.js` | Export tab: CSV download (date range, point picker, resolution, display/stored units; pure helpers tested in node) | browser |
| `static/units.js` | SI math / imperial-or-SI display (`ofddUnits`); the header toggle sets `localStorage["openfdd-units"]` | browser + FDD hook |
| `static/energy.js` | Demand, monthly energy, degree-day baseline, M&V, EUI / peers | browser |
| `static/app-core.js`, `charts.js`, `theme.js`, `base.css`, `style.css`, `vendor/` | The shared dashboard shell (top bar, tab router, Overview, Charts, Points, BACnet Server, Model & RDF), chart catalog, light/dark themes, CSS base + Full's own rules, vendored ECharts 6.1.0 (ESM). `app.js` adds the Full-only tabs (FDD, RCx, Export) | browser |
| `hooks/fdd.js` | Hourly FDD: bind roles, read NF history (5-min grid), run the SQL pack, write result points, optional BACnet AVs | NF Node runtime |
| `hooks/lib/engines.js` | SQL engines: `sqlite` (sql.js, vendored in `hooks/vendor/`) and `pglite` | FDD hook |
| `hooks/weather.js` | **Shared with Lite** (one source). Open-Meteo outdoor air every 20 min → global variables (site lat/lon from NF) | NF Node runtime |
| `rules/` | `pack-postgres.json` / `pack-sqlite.json` (built from `sql/fdd`), role overrides, NF class list | build scripts |
| `rcx-parity.json` | Where every chart of the old central UI lives now (CI-enforced) | `tests/parity.test.mjs` |
| `dev/mock-nf.mjs` | Mock NF + synthetic two-site building for local development | developers |
| `tests/` | `node --test nf-app/tests/*.test.mjs` | CI (`nf-app-ci.yml`) |

## Shared code (Full and Lite)

The code both editions have in common has one source under `shared/`: the dashboard shell (`app-core.js`: top bar, equip
pickers, tab router, Overview, Charts, Points, BACnet Server, Model & RDF, live loop), `charts.js`, `theme.js`,
`chart-page.js`, `tree.js`, `base.css`, `nf.js`, `model.js`, `theme-init.js`, `tree.css`, `version.js`, the pager
`paging.js`, `settings.js`, the weather hook and `shapes.d.ts`. Edit the source and run `python scripts/nf/sync_shared.py`;
`--check` and `tests/test_shared_sources.py` fail when a copy in `nf-app/` or `lite/` is stale or hand-edited. What stays
per edition: `app.js` (Full registers the FDD, RCx and Export tabs, the units toggle and Run FDD through the `ofddTabs` /
`ofddEquipScoped` / `ofddWire` registries of `app-core.js`; Lite only starts the shell), the three HTML pages (script
lists differ: Full loads the ES-module ECharts, Lite the UMD build), `style.css` (edition rules on top of `base.css`) and
the Full-only files (`fdd*.js`, `rcx*.js`, `energy.js`, `export.js`, `sparql.js`, `units.js`, ...). Lite stays light: it
does not load any FDD / RCx / SPARQL code. The default range of every history view is the last 7 days
(`DEFAULT_RANGE_PRESET` in `charts.js`).

## Develop

```bash
node nf-app/dev/mock-nf.mjs                      # http://127.0.0.1:8765/api/v1/apps/static/open-fdd/
node --test nf-app/tests/*.test.mjs              # unit + parity tests (no NF needed)
python3 scripts/nf/build_rule_catalog.py         # after editing sql/fdd registry/role map or rules/role_overrides.json
python3 scripts/nf/build_sql_pack.py             # after editing sql/fdd rules (re-renders + re-translates both packs)
node scripts/nf/measure_engines.mjs sqlite 1 7   # engine memory/time check
```

Add a chart: register it in one of the view modules with `rcxView({ id, group, title, kinds, roles, scope, render })`
using role names from `fdd-catalog.json`; show faults only with `rcxWithFaultLane(option, [{ name, data }])`.

## Deploy

```bash
# env file outside git (see ../.env.example): NF_CONSOLE_URL, CONSOLE_USERNAME, CONSOLE_PASSWORD
python3 scripts/nf/hooks/nf_app_sync.py --env ~/.secrets/nf_site_console.env push nf-app/app.json             # files + hooks
python3 scripts/nf/hooks/nf_app_sync.py --env ~/.secrets/nf_site_console.env push nf-app/app.json --hook fdd  # files + one hook
python3 scripts/nf/hooks/nf_app_sync.py --env ~/.secrets/nf_site_console.env push nf-app/app.json --skip-hooks # UI only
python3 scripts/nf/hooks/nf_app_sync.py --env ~/.secrets/nf_site_console.env run  nf-app/app.json --hook fdd  # run now
```

NF derives an app's id from its **name**, so `application.id` must equal the slug of `application.name` (CI
checks it). Static files are cached 5 minutes; `nf_app_sync.py` stamps js/css URLs with a content hash on push.

## Vendored libraries

| Library | Version | File | sha256 |
|---|---|---|---|
| ECharts (ESM build, `dist/echarts.esm.min.mjs` from npm) | 6.1.0 | `static/vendor/echarts.esm.min.js` | `28515f26aa57f87eb1e4ed4eb446927eaf329b5f5e02b4bfd4b0264fea40d1da` |
| sql.js | 1.15.1 | `hooks/vendor/sql.js/sql-wasm.{js,wasm}` | from `npm install` (`package-lock.json`) |
| @electric-sql/pglite | 0.5.11 | npm only (`package.json`) | `package-lock.json` |

Supply-chain rule: never take a release younger than two weeks (sql.js 1.15.2 and pglite 0.5.12+ were too new on 2026-11-06).
Caddy front door: `caddy:2.11.7-alpine`, pinned in `deploy/nf-caddy/docker-compose.yml`.

## TimescaleDB full edition (optional)

`hooks/lib/timescale.js`, `hooks/history.js` and `timescale/` run the rule pack inside NF's TimescaleDB connector
database. It is selected by hook **config** (`engine: "timescale"` plus a `timescale` block in the `fdd` and `history` hook
config), not by enabling the connector; a missing block is an error, never a silent fallback. Retention only drops chunks
of Open-FDD's own tables (schema `openfdd`); NF's `data` table or other apps' tables are trimmed only if listed in
`openfdd.config.retention_allowlist`. Use a separate installer role (runs `install.sql`) and a runtime role (SELECT on NF's
tables, write on schema `openfdd`). Setup, grants, `retention_preview()`, upgrade and tests:
[`timescale/README.md`](timescale/README.md); config examples: [docs/install.md](../docs/install.md).

## Hooks and data surface

The whole "API" of the app is these NF hooks (`POST /api/v1/apps/<id>/hooks/<hook>`, answer from `.../runs?include_results=true`) plus the 17 NF REST paths the pages and hooks consume. There is no Open-FDD HTTP server.

| Hook | Edition | Mode | Caller | Reads / writes |
|---|---|---|---|---|
| `fdd` | Full | scheduled hourly (+ run-now) | dashboard (run-now, runs), installer, `export.js`, `rcx.js` | reads NF points + history; writes result points (and `openfdd.fdd_results` with the Timescale engine) |
| `weather` (Full) / `open-meteo-weather` (Lite) | both | scheduled every 20 min | writes the `*_web` global variables the pages and rules read | one shared source (`shared/hooks/open_meteo_weather.js`); writes 3 global variables; both editions also export them through the `exporters` list (default `bacnet-av`, only when NF's BACnet server is present; app option `bacnetMirror: false` removes it). App option `weather: false` = off: no outbound request, `{skipped, reason: "weather disabled"}`, rules fall back to the local OA sensor ([install reference](../docs/install.md)) |
| `sparql` | Full | on request | agents and docs (the browser runs the same engine in `static/sparql.js`) | read-only |
| `analytics` | Full | on request | agents (`rcx-overview.js` exposes the entry points) | read-only; 6 tools via `args.tool`: `analyze_ahu_weekly_runtime`, `analyze_mechanical_cooling`, `analyze_economizer`, `get_fdd_fault_timeline`, `resolve_equipment_roles`, `explain_missing_rcx_view` |
| `schema` | Full | on request | installer / `doctor` | read-only (`BEGIN TRANSACTION READ ONLY`); reports the Timescale `schema_version` |
| `history` | Full | on request | `doctor` and agents (charts read `/api/v1/point/data` directly); agent-only API | read-only; server-side bucketed history from Timescale |

Tables the **Full** edition creates, only when the optional Timescale engine is installed (`timescale/install.sql`; `SCHEMA_VERSION` 3):

| Object | Kind | Written by | Read by |
|---|---|---|---|
| `openfdd.config` | table | `install.sql` seeds | `hooks/lib/timescale.js`, the retention functions, `doctor` |
| `fdd.point` | table | `fdd` hook (synced per equipment before each load) | **core schema** (`sql/fdd/schema/core.sql`): one row per bound point with its SI `unit`, `si_scale` / `si_offset` and `role`; read by `fdd.input_sample` |
| `fdd.rule_result` | hypertable (`window_end`, 30 d) | `fdd` hook (upsert per run) | **core schema; integration output**: BI tools and downstream apps read it. PK `(site_id, equipment_id, rule_id, subject_key, window_start, window_end, rule_hash, config_hash)`; `status` PASS/FAULT/INCONCLUSIVE/SKIPPED/ERROR/STALE, `fault_hours`, `covered_hours`, `fault_pct`, `metrics`, `diagnostics` |
| `fdd.rule_config` | table | tuning hook (writes), `fdd` hook (reads) | **core schema**: append-only tuning revisions (one active per scope); Open-FDD stores sweep role-limit overrides as `rule_id` `SV-LIMITS` (#1589) |
| `openfdd.nf_samples` | view | n/a | NF's samples in native units (`history_buckets`, newest-sample lookup) |
| `fdd.input_sample` | view | n/a | SI samples of the bound points (`value * si_scale + si_offset`); the loader reads it (`adapter_nf.sql`) |

The Lite edition and the `sqlite` / `pglite` engines create no persistent tables. Each run builds 5 per-run scratch (TEMP) relations from the SQL input contract (`sql/fdd/input_contract.json`, version 3): `history`, `weather`, `sensor_history`, `utility_interval`, `utility_monthly`.

`sql/fdd/schema/core.sql` is the shared core schema (`fdd.point`, `fdd.rule_result`, `fdd.rule_config`): the NF app installs it, and downstream applications vendor it byte for byte (it ships in the wheel as `open_fdd/data/core.sql`). Schema version 4 (5.0.16) replaced `openfdd.fdd_results` and `openfdd.retention_log` with it; see [`docs/upgrade-5x.md`](../docs/upgrade-5x.md).

## Rules this app follows

- **Nothing site-specific in code:** sites, equips and points come from NF's Haystack model.
- **One FDD math:** `sql/fdd` → packs; the SQLite pack must match Postgres on every rule (`engines.test.mjs`).
- **Faults look the same everywhere:** a 0/1 lane at the bottom of the plot (`rcxWithFaultLane`).
- **Strict CSP:** no inline scripts/styles; all assets self-hosted except the pinned Clerk login script on the portal path.
- **Light on the box:** NF resamples history; small edges use the SQLite engine; heavy work never runs on the box.
