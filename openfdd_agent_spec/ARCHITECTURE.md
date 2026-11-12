# Architecture (5.0)

Open-FDD is an NF app. NF owns the field bus (BACnet, Modbus), the point model (Haystack tags), history, auth,
remote access (Normal Online) and config backups. Open-FDD adds a UI and hooks. Decision: ADR-014 in `docs/architecture/`.

## Pieces

| Piece | Where | Runs in |
|---|---|---|
| Static UI | `nf-app/static/` (served by NF at `/api/v1/apps/static/open-fdd/`) | the browser; plain JS, strict CSP, vendored ECharts |
| `fdd` hook | `nf-app/hooks/fdd.js`, hourly | NF Node runtime; SQL rules in SQLite-WASM (sql.js) or PGlite |
| `weather` hook | `nf-app/hooks/weather.js`, every 20 min | NF Node runtime; Open-Meteo to global variables |
| `sparql` hook | `nf-app/hooks/sparql.js`, on request | NF Node runtime; Oxigraph over the model's Turtle |
| `analytics` hook | `nf-app/hooks/analytics.js`, on request (`args.tool`) | NF Node runtime; read-only agent tools (weekly runtime, cooling bins, economizer, fault timeline, roles, view explanations) on the dashboard's own `static/*.js`; CLI `open-fdd-nf analyze` |
| Rule math | `sql/fdd/` (Postgres SQL) to `nf-app/rules/pack-*.json` | built by `scripts/nf/build_*.py` |
| Manifest | `nf-app/app.json` (application, file map, hooks) | read by `nf_app_sync.py` / the NF MCP |

The UI and the `fdd` hook share code: the hook loads `static/model.js`, `fdd.js`, `units.js` and the catalog, so they
cannot disagree about binding or units. NF caches static files for 5 minutes.

## Editions

- **Full** (`nf-app/`, app id `open-fdd`): UI tabs Overview, Charts, FDD, RCx, Points, Export, BACnet Server, Model and RDF
  (with SPARQL); hooks `fdd`, `weather`, `sparql`. Engine `sqlite` (small) or `pglite` (4 GB+); `engine: "auto"` picks.
- **Lite** (`lite/`, app id `open-fdd-lite`): no FDD engine and no npm dependencies; Overview, Charts, Points, BACnet
  Server, Model and RDF; `weather` hook with an optional BACnet mirror. For 1 GB boxes.

## Data flow

```
NF model (Haystack) --point/query--> bind roles (class, else markers; per equip, per site)
NF history --point/data (window=300s, AVERAGE)--> 5-minute grid, SI --> SQL pack (one query per rule)
  --> rows --> result points written to NF (one per equip and rule) --> trended, charted, in the RDF,
      optionally served as BACnet AVs (config.bacnet.enabled)
```

The UI reads the same model and history through the NF API and draws charts. Faults are drawn from the result points
as a 0/1 lane at the bottom of each plot.

## RDF and SPARQL

`modelToTurtle()` (`static/model.js`) turns the model into Turtle: sites, equips, devices, points, markers, refs and
one Brick `ref:TimeseriesReference` per point (`ref:hasTimeseriesId` = NF point uuid). The UI SPARQL panel loads it into
Oxigraph (WASM, vendored, `wasm-unsafe-eval` in the CSP). The `sparql` hook does the same server-side:
`POST /api/v1/apps/open-fdd/hooks/sparql` with `args.query` and `args.format` (`json`, `csv`, `turtle`); read the
answer from `.../hooks/sparql/runs?include_results=true`. `tools/rdf-check` validates the export with Oxigraph and rdflib.

## Hooks and data surface

The whole "API" of the app is these NF hooks (`POST /api/v1/apps/<id>/hooks/<hook>`, answer from `.../runs?include_results=true`) plus the 17 NF REST paths the pages and hooks consume. There is no Open-FDD HTTP server.

| Hook | Edition | Mode | Caller | Reads / writes |
|---|---|---|---|---|
| `fdd` | Full | scheduled hourly (+ run-now) | dashboard (run-now, runs), installer, `export.js`, `rcx.js` | reads NF points + history; writes result points (and `openfdd.fdd_results` with the Timescale engine) |
| `weather` (Full) / `open-meteo-weather` (Lite) | both | scheduled every 20 min | writes the `*_web` global variables the pages and rules read | one shared source (`shared/hooks/open_meteo_weather.js`); writes 3 global variables; both editions mirror them to 3 BACnet AVs by default (`bacnetMirror:false` turns it off) |
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
| `fdd.rule_config` | table | created, unused by Open-FDD | **core schema**: append-only tuning revisions (one active per scope) for integrators that store tuning |
| `openfdd.nf_samples` | view | n/a | NF's samples in native units (`history_buckets`, newest-sample lookup) |
| `fdd.input_sample` | view | n/a | SI samples of the bound points (`value * si_scale + si_offset`); the loader reads it (`adapter_nf.sql`) |

The Lite edition and the `sqlite` / `pglite` engines create no persistent tables. Each run builds 5 per-run scratch (TEMP) relations from the SQL input contract (`sql/fdd/input_contract.json`, version 3): `history`, `weather`, `sensor_history`, `utility_interval`, `utility_monthly`.

`sql/fdd/schema/core.sql` is the shared core schema (`fdd.point`, `fdd.rule_result`, `fdd.rule_config`): the NF app installs it, and downstream applications vendor it byte for byte (it ships in the wheel as `open_fdd/data/core.sql`). Schema version 4 (5.0.16) replaced `openfdd.fdd_results` and `openfdd.retention_log` with it; see [`docs/operations/nf/migrate-5.x.md`](../docs/operations/nf/migrate-5.x.md).

## Constraints

- No site-specific code; the model in NF is the only configuration.
- NF's Envoy ends pushed stream batches without a final chunk behind proxies; `nf.js` treats that as a normal end.
- Through the Normal Online portal API-key tokens cannot read `/api/v1/bacnet/*`; the page sends the console's Clerk token.
