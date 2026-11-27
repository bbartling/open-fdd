---
title: Data model
nav_order: 2
---

# Data model

Rules are driven by the model in NF. Open-FDD finds sites, equipment and points from NF's Haystack tags. It has no site-specific
code or settings: tag the model in NF, then reload the app.

| Record | Fields Open-FDD uses |
|---|---|
| Site | latitude, longitude, timezone, optional area and `areaUnit` |
| Equipment | `siteRef`, equipment markers such as `ahu`, `vav`, `chiller` |
| Point | `siteRef`, `equipRef`, `class`, markers, `kind`, `unit`, history |

Trend every point a chart or rule uses. Site coordinates feed the weather hook; floor area feeds energy-intensity charts.

## Roles bind points to rule inputs

A rule asks for named roles, for example supply-air temperature or fan command. A point fills a role when its NF class matches one
of the role's classes, or when it carries every marker of the role. Class wins because it is more specific.

- Markers are one comma-separated string in NF. Setting a class does not add markers.
- Equipment kinds come from the equipment markers. Haystack 4 plant conjuncts work like the camelCase tags: a
  `hot-water-plant` or `steam-plant` (or `hot`+`water`+`plant`) is a boiler, a `chilled-water-plant` a chilled-water plant,
  a `condenser-water-plant` a cooling tower. A combined plant (`hot`+`chilled`+`water`+`plant`) has both kinds: both rule
  families apply, each to the points it finds. Weather points fill weather roles only.
- The role-to-class and marker map is `nf-app/static/fdd-catalog.json`. The [rule catalog](rules/) and
  [cookbooks](rules/sql-cookbook.html) list each rule's roles.
- **Run proof** is the one role no point fills by class: it is resolved from the model. An equipment proves itself by its own fan,
  pump, chiller or compressor status, then command; otherwise by the equipment that feeds it, through `airRef` (a VAV to its AHU),
  `chilledWaterRef` or `hotWaterRef` (a water loop to its pump), or RDF `brick:isFedBy` / `brick:feeds`. With none, rules that
  need proof are skipped with `no_run_proof`. See the [run proof gate](rules/sql-cookbook.html#run-proof).
- The FDD and RCx pages show missing required roles. Fix the class or markers in NF, check the point has history and a unit, reload.

## ASHRAE 223P

223P is the role contract. Haystack tags are an optional overlay for binding and display.

[`roles/openfdd-roles.json`](https://github.com/bbartling/open-fdd/blob/master/roles/openfdd-roles.json) (`openfdd-roles` 1.0.0-draft.1, 86 roles) is one 223P property pattern per role, named `role`, with a QUDT local name. Seventeen roles use an `ext:` term. The rules still read `legacy_keys` in `sql/fdd/input_contract.json`. A point binds by NF class, else by the role's markers. `ofddRole` (Turtle `local:ofddRole`) or a SPARQL `?role` overrides that. The RDF export and the SPARQL hooks share that Turtle graph ([RDF and SPARQL](#rdf-and-sparql)).

| Piece | Where it lives |
|---|---|
| Role name | `role` in `roles/openfdd-roles.json` |
| QUDT unit | `unit` local name |
| Haystack overlay | `haystack` classes and markers |
| Rule column today | `legacy_keys`, then `input_contract.json` |
| Model export | Turtle, subject `urn:nf:<uuid>`; SPARQL over that graph |

## Units are SI-first

The engineer declares each point's unit in NF. Ingest converts supported units to SI; rules and stored results stay SI. Imperial
is display-only. Unknown or incompatible units are skipped, never guessed from the value: a unitless 0.5 could be a fraction or a percent.

| Quantity | SI unit |
|---|---|
| Temperature / difference | °C / Δ°C |
| Pressure | Pa |
| Flow | L/s |
| Power / energy | kW / kWh |
| Relative humidity | %RH, 0-100 |
| Commands, positions | fraction, 0-1 |
| Status | 0/1 |

Accepted input units, imperial display and per-rule units are in the [units convention](rules/sql-cookbook.html#units-convention). The
conversion table is `open_fdd/data/units.json`, shared by the browser (`nf-app/static/units.js`) and Python (`open_fdd/nf/units.py`).
Sensor-validation rules also require the sensor's declared unit to match its SI quantity.

## RDF and SPARQL

The Model and RDF tab exports the Haystack model as Turtle with stable subjects. References resolve within their site and each point
links to its NF time-series id. The tab flags dangling references and non-standard tags.

Subjects are `urn:nf:<NF uuid>` (base `urn:nf:`). They depend neither on the host the page or hook was reached through nor
on the sites, so adding a site rewrites no subject. The tab, the `rdf`, `sparql` and `sparql-data` hooks and the Python
client give the same IRIs; the hooks take `base` to override it. A point IRI from an older `urn:nf:<host>:<uuid>` or
`urn:nf:site:<site>:<uuid>` export still names its point in `sparql-data` and `open_fdd.nf.sparql_data`.

ASHRAE 223P is the rule-input contract (`roles/openfdd-roles.json`, 1.1.0-draft.1). Haystack defs 4.0.0 are only the
overlay this export writes, and those IRIs are versioned (`…/def/phIoT/4.0.0#`). The app does not resolve `owl:imports`
or run SHACL. CI downloads the sha256-pinned closure (223P, QUDT 3.4.0, SHACL, SKOS and VAEM) into a cache, then
OntoEnv resolves those imports with the network off and Shifty validates the role file.
SPARQL answers use Oxigraph 0.5.13. rdflib 7.6.0 parses Turtle and does not evaluate those queries.

| Use | How |
|---|---|
| Check a Turtle file | `pip install rdflib==7.6.0 pyoxigraph==0.5.13`, then `python tools/rdf-check/check_ttl.py model.ttl` |
| Build Turtle from a fixture | `node tools/rdf-check/gen_ttl.js fixture.json fixture.ttl` (fixture has a `records` array) |
| Query in the browser | SELECT, ASK, CONSTRUCT or DESCRIBE over the loaded model; results are capped and download as CSV |
| Query from code (Full) | `POST /api/v1/apps/{app-id}/hooks/sparql`, then read `GET /api/v1/apps/{app-id}/hooks/sparql/runs?include_results=true` |

Updates and remote `SERVICE` queries are refused. Request and response shapes are in the [API reference](fdd-data-access.html).

### SPARQL to trend data to pandas (both editions)

A client script can ask the site model which points it wants and get their history back in one step, then run the
pandas reference rules on its own machine:

| Edition | Path |
|---|---|
| Full | `sparql-data` hook: SELECT / ASK only, the matched points' history from NF `point/data` (raw or resampled) or Timescale (`source=timescale`), at most 200 points a page (`pointOffset`), at most 190 000 UTF-8 bytes an answer (cut on a timestamp, continue from `next_from`), every page pinned to one model `snapshot` |
| Lite | `rdf` hook hands over the model Turtle in pages; the client runs the query with pyoxigraph (same SELECT / ASK policy and the same answers as the Full hook) and reads history through NF `point/data` |

```bash
open-fdd-nf sparql examples/sparql_data/ahu_points.rq --days 7 --rules FC1,FC3
```

```python
from open_fdd.nf import NFClient
from open_fdd.nf import sparql_data as sd

client = NFClient.from_env()
answer = sd.fetch_auto(client, open("ahu_points.rq").read(), start, end)   # every page, one snapshot
frames = sd.frames(answer)                                                 # SI frames, same code as equipment_frames
print(sd.run_rules(frames))                                                # the open_fdd.rules pandas functions
```

A point binds to a rule input by the query's `?role` column, else its NF attr `ofddRole` (exported as `local:ofddRole`),
else the catalog binding (NF class, then markers). The client holds no fault math: frames are built by
`open_fdd.nf.model.frames_from_samples` and the rules are the package's. The parity harness proves it: the SPARQL
client through the shipped hook gives the same results as the pandas oracle and the SQL pack (see
[parity](rules/parity.html)).
