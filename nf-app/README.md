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
| `static/fdd.js`, `fdd-catalog.json` | Rule catalog + role binding (NF class, else Haystack markers) | browser + FDD hook |
| `static/rcx.js` | RCx view registry, binding, shared math, **the fault lane** (`rcxWithFaultLane`) | browser |
| `static/fdd-plots.js` | Per-rule plot, OAT-METEO, sensor health / sensor faults | browser |
| `static/rcx-overview.js` | Weekly runtimes, mechanical cooling, economizer, BAS vs web OAT | browser |
| `static/rcx-presets.js` | The 18 RCx presets + VAV health | browser |
| `static/export.js` | Export tab: CSV download (date range, point picker, resolution, display/stored units; pure helpers tested in node) | browser |
| `static/units.js` | SI math / imperial-or-SI display (`ofddUnits`); the header toggle sets `localStorage["openfdd-units"]` | browser + FDD hook |
| `static/energy.js` | Demand, monthly energy, degree-day baseline, M&V, EUI / peers | browser |
| `static/charts.js`, `theme*.js`, `style.css`, `vendor/` | Charts tab, light/dark themes, vendored ECharts 6.1.0 (ESM) | browser |
| `hooks/fdd.js` | Hourly FDD: bind roles, read NF history (5-min grid), run the SQL pack, write result points, optional BACnet AVs | NF Node runtime |
| `hooks/lib/engines.js` | SQL engines: `sqlite` (sql.js, vendored in `hooks/vendor/`) and `pglite` | FDD hook |
| `hooks/weather.js` | **Shared with Lite** (one source). Open-Meteo outdoor air every 20 min → global variables (site lat/lon from NF) | NF Node runtime |
| `rules/` | `pack-postgres.json` / `pack-sqlite.json` (built from `sql/fdd`), role overrides, NF class list | build scripts |
| `rcx-parity.json` | Where every chart of the old central UI lives now (CI-enforced) | `tests/parity.test.mjs` |
| `dev/mock-nf.mjs` | Mock NF + synthetic two-site building for local development | developers |
| `tests/` | `node --test nf-app/tests/*.test.mjs` | CI (`nf-app-ci.yml`) |

## Shared code (Full and Lite)

The files both editions had hand-copied now have one source under `shared/` (`nf.js`, `model.js`, `theme-init.js`,
`tree.css`, `version.js`, the pager `paging.js`, `settings.js`, the weather hook, `shapes.d.ts`). Edit the source and run
`python scripts/nf/sync_shared.py`; `--check` and `tests/test_shared_sources.py` fail when a copy in `nf-app/` or `lite/` is
stale or hand-edited. The remaining UI files (`app.js`, `charts.js`, `index.html`, `chart.html`, `tree.html`, `tree.js`,
`chart-page.js`, `style.css`) are genuinely different per edition (Full has the FDD, RCx, SPARQL and Export tabs and the
`theme.js` chart layer; Lite has `lite-theme.js`) and stay separate.

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
| `weather` (Full) / `open-meteo-weather` (Lite) | both | scheduled every 20 min | writes the `*_web` global variables the pages and rules read | one shared source (`shared/hooks/open_meteo_weather.js`); writes 3 global variables; Lite (default; app option `bacnetMirror` overrides) also mirrors them to 3 BACnet AVs |
| `sparql` | Full | on request | agents and docs (the browser runs the same engine in `static/sparql.js`) | read-only |
| `analytics` | Full | on request | agents (`rcx-overview.js` exposes the entry points) | read-only; 6 tools via `args.tool`: `analyze_ahu_weekly_runtime`, `analyze_mechanical_cooling`, `analyze_economizer`, `get_fdd_fault_timeline`, `resolve_equipment_roles`, `explain_missing_rcx_view` |
| `schema` | Full | on request | installer / `doctor` | read-only (`BEGIN TRANSACTION READ ONLY`); reports the Timescale `schema_version` |
| `history` | Full | on request | `doctor` and agents (charts read `/api/v1/point/data` directly); agent-only API | read-only; server-side bucketed history from Timescale |

Tables the **Full** edition creates, only when the optional Timescale engine is installed (`timescale/install.sql`; `SCHEMA_VERSION` 3):

| Object | Kind | Written by | Read by |
|---|---|---|---|
| `openfdd.config` | table | `install.sql` seeds | `hooks/lib/timescale.js`, the retention functions, `doctor` |
| `openfdd.fdd_results` | hypertable | `fdd` hook (upsert per run) | **integration output**: BI tools and downstream apps read it; the dashboard reads the hook's result points instead. PK `(run_ts, equip, rule_id, sensor_ref)`; columns `site`, `fault_pct`, `fault_hours`, `covered_hours`, `metric` (jsonb), `engine`, `window_start`, `window_end`, `role` |
| `openfdd.retention_log` | table | `openfdd.retention_run()` | audit trail (tests, operators) |
| `openfdd.nf_samples` | view | n/a | `hooks/lib/timescale.js`, `hooks/lib/engines.js` (adapter over NF's sample table) |

The Lite edition and the `sqlite` / `pglite` engines create no persistent tables. Each run builds 5 per-run scratch (TEMP) relations from the SQL input contract (`sql/fdd/input_contract.json`, version 2): `history`, `weather`, `sensor_history`, `utility_interval`, `utility_monthly`.

`sql/fdd/tuning_storage.sql` (`fdd.rule_config_revision`, `fdd.active_rule_config`, `fdd.rule_result`) is **not** part of the above: it is the tuning storage contract that integrators adopt (see [`sql/fdd/README.md`](../sql/fdd/README.md)); no Open-FDD component reads or writes those tables.

## Rules this app follows

- **Nothing site-specific in code:** sites, equips and points come from NF's Haystack model.
- **One FDD math:** `sql/fdd` → packs; the SQLite pack must match Postgres on every rule (`engines.test.mjs`).
- **Faults look the same everywhere:** a 0/1 lane at the bottom of the plot (`rcxWithFaultLane`).
- **Strict CSP:** no inline scripts/styles; all assets self-hosted except the pinned Clerk login script on the portal path.
- **Light on the box:** NF resamples history; small edges use the SQLite engine; heavy work never runs on the box.
