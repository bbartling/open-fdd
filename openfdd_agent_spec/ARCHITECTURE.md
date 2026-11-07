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

## Constraints

- No site-specific code; the model in NF is the only configuration.
- NF's Envoy ends pushed stream batches without a final chunk behind proxies; `nf.js` treats that as a normal end.
- Through the Normal Online portal API-key tokens cannot read `/api/v1/bacnet/*`; the page sends the console's Clerk token.
