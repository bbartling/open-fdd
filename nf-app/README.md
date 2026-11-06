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
| `static/nf.js` | NF access: login (LAN or Normal Online/Clerk), `api()`, live push stream | browser |
| `static/model.js` | Haystack model loader + RDF/Turtle export with time-series refs | browser + FDD hook |
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
| `hooks/weather.js` | Open-Meteo outdoor air every 20 min → global variables (site lat/lon from NF) | NF Node runtime |
| `rules/` | `pack-postgres.json` / `pack-sqlite.json` (built from `sql/fdd`), role overrides, NF class list | build scripts |
| `rcx-parity.json` | Where every chart of the old central UI lives now (CI-enforced) | `tests/parity.test.mjs` |
| `dev/mock-nf.mjs` | Mock NF + synthetic two-site building for local development | developers |
| `tests/` | `node --test nf-app/tests/*.test.mjs` | CI (`nf-app-ci.yml`) |

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

## Rules this app follows

- **Nothing site-specific in code:** sites, equips and points come from NF's Haystack model.
- **One FDD math:** `sql/fdd` → packs; the SQLite pack must match Postgres on every rule (`engines.test.mjs`).
- **Faults look the same everywhere:** a 0/1 lane at the bottom of the plot (`rcxWithFaultLane`).
- **Strict CSP:** no inline scripts/styles, no CDN at runtime.
- **Light on the box:** NF resamples history; small edges use the SQLite engine; heavy work never runs on the box.
