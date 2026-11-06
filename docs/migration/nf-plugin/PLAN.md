---
title: Migration plan
parent: Architecture
nav_order: 2
---

> Historical record. `archive/central-v4/` was later removed entirely; the 4.x line is tag `v4.0.11-central`.

# Open-FDD → Normal Framework plugin: migration plan

Decision record: [ADR-014](../../architecture/adr-014-open-fdd-as-nf-plugin.html). Branches: `nf-plugin/slice-N`.
Dev bench: Raspberry Pi 3 "bosspi" (NF 3.10.9-1, 1 GB — **edge-lite only**). Production target: an
NF edge with ≥ 4 GB RAM and NF's TimescaleDB integration (**full**).

## Target shape

```
nf-app/                      one NF application, id "open-fdd"
  app.json                   manifest for scripts/nf/hooks/nf_app_sync.py (app, files, hooks)
  static/                    Open-FDD UI (served by NF at /api/v1/apps/static/open-fdd/)
    index.html …             tabs: Overview · Charts · FDD · RCx · Points · BACnet · Model & RDF
    nf.js model.js charts.js theme.js app.js …   NF data layer (query, resampled history, live push)
    vendor/echarts.esm.min.js
  hooks/
    weather.js               Open-Meteo → global variables (site lat/lon read from NF /api/v1/sites)
    fdd.js                   rule runner: edge-lite (NF history) or full (TimescaleDB)
  rules/                     generated from sql/fdd/postgres/rules + registry.yaml + role_map.json
deploy/caddy/                front door (plain HTTP default, Caddyfile.tls option)
```

## Slices

| # | Slice | Done when |
|---|---|---|
| 0 | ADR-014 + this plan | reviewed |
| 1 | **App skeleton**: `nf-app/` with the Open-FDD Edge UI (NF-native data layer, light/dark, strict CSP, ESM ECharts, RDF export), the weather hook, a manifest `nf_app_sync.py` can push; node tests for the app JS | app deployed to the bench as `open-fdd`, all tabs render from the live NF model, RDF check passes |
| 2 | **Role binding**: map `role_map.json` roles to NF Haystack classes/markers; "Rule inputs" view (which rules each equip can run, missing roles) | bench furnace shows its runnable rules; coverage report matches `registry.yaml` |
| 3 | **FDD engine, edge-lite**: `fdd.js` hook builds the `history` relation from NF resampled data and runs the SQL pack in an embedded Postgres (PGlite) — memory measured on the Pi first; fallback = declared subset | hourly run on the bench; fault points written back to NF (`fault` marker, `ruleRef`, `equipRef`) |
| 4 | **FDD UI**: fault lanes on charts, FDD tab (fault hours per rule/equip), RCx tab ported from central's static UI onto NF data | parity rows for AHU RCx charts on bench data |
| 5 | **Full profile**: NF TimescaleDB northbound → hook runs the same pack in TimescaleDB, results in schema `openfdd` + NF fault points; long-range charts from TimescaleDB | runs on a ≥ 4 GB NF box with 30+ days of data |
| 6 | **RDF with external time-series refs**: each point links to its NF history endpoint (and TimescaleDB rows in full profile); SPARQL-ready Turtle validated with Oxigraph in CI | `tools/rdf-check` green in CI |
| 7 | **Front door + packaging**: `deploy/caddy` (from the NF_NOTES bench), install docs, MCP deploy recipe | fresh NF box → Open-FDD in one documented run |
| 8 | **Archive central**: `git mv` `services/central`, provider/ingest crates, portal compose, central CI to `archive/central-v4/` with README + restore notes; CI switches to plugin gates | `master` builds only the plugin; release notes |

## Answered by NF's hooks guide (NF MCP `nf://docs/hooks-guide`, 2026-11-05)

- **Per-equipment rule runs:** a hook in *equipment mode* (`equipment_type_id`, `group_keys: ["equipRef"]`,
  `query_filters: { class: [...] }`) is called **once per equipment** with only that equipment's points;
  `sdk.groupKey` is the `equipRef`. → `fdd.js` binds rule roles to Haystack classes this way (slice 2/3).
- **Fault outputs:** *group variables* are per-group points on the `automation` layer with stable UUIDs
  (`MD5(appId + hookId + label + groupName)`), trended on every write → one fault flag / fault-hours
  point per rule per equipment, no manual point creation.
- **Triggers:** `scheduled` (rrule with `DTSTART`), `on_request`, `on_data` (new values, ≤ 1/s), `disabled`.
- **Settings:** hooks receive `config` (e.g. `site` for the weather hook, rule thresholds) and `args`.
- **npm dependencies:** allowed via `package.json` + `install_dependencies` (the SDK is pre-installed).
- **Helpers:** `point.trueFor("5m", predicate)`, `point.isChanged()`, `sdk.http` (Axios) to NF's REST API.

## Open questions (answer before the slice that needs them)

- **Hook runtime limits** (slice 3): max run time and memory cap of `applications-sdk` (Node
  `--max-old-space-size=256` seen on the bench).
- **PGlite on a Pi 3** (slice 3): WASM Postgres memory/CPU; acceptable rule-run time for 7 days × N equips.
- **NF TimescaleDB integration** (slice 5): exact table/column shapes (`instances`, `points`, `data`,
  `layer_*` views), how a hook reaches the database (connection settings as app config secrets).
- **Portal auth for app API calls** (slice 1): pages already use the console's Clerk token through
  Normal Online; confirm hooks need nothing beyond `auth.apiKey.scopes`.
- **Licensing**: Open-FDD stays open source; the plugin runs on any licensed NF.

Slice 7 notes: front door in `deploy/nf-caddy/` (Caddy: dashboard and read-only API open, console/apps/writes basic auth, optional TLS); one-run install and MCP recipe in `docs/install/nf-plugin.md`. Caddyfiles not yet validated (Docker daemon was not running).

## Slice 6 notes: RDF with external time-series refs

- `modelToTurtle()` (`nf-app/static/model.js`) gives every exported point a Brick `ref:` reference:
  `ref:hasExternalReference [ a ref:TimeseriesReference ; ref:hasTimeseriesId "<NF point uuid>" ;
  ref:storedAt local:store_nf ; rdfs:seeAlso <{origin}/api/v1/point/data?uuids=<uuid>> ]`.
- `local:store_nf` (`a ref:Database`) is defined in the graph; the URL base is the page origin at export
  time (or `opts.nfBase`), never a hard-coded host. Without either, only the uuid is emitted.
- Full-profile hook: `modelToTurtle(model, base, { timescale: { label, uri } })` adds a second reference per
  point stored at `local:store_timescaledb` (same uuid). Not wired to any UI yet.
- CI: `tools/rdf-check` (`gen_ttl.js` on `fixtures/model.json`, then `check_ttl.py` with Oxigraph + rdflib)
  checks parse, no dangling refs/orphans, and exactly one NF reference with a uuid per point.
