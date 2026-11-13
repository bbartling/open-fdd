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
- Equipment kinds come from the equipment markers. Weather points fill weather roles only.
- The role-to-class and marker map is `nf-app/static/fdd-catalog.json`. The [rule catalog](rules/) and
  [cookbooks](rules/sql-cookbook.html) list each rule's roles.
- The FDD and RCx pages show missing required roles. Fix the class or markers in NF, check the point has history and a unit, reload.

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

| Use | How |
|---|---|
| Check a Turtle file | `pip install rdflib pyoxigraph`, then `python tools/rdf-check/check_ttl.py model.ttl` |
| Build Turtle from a fixture | `node tools/rdf-check/gen_ttl.js fixture.json fixture.ttl` (fixture has a `records` array) |
| Query in the browser | SELECT, ASK, CONSTRUCT or DESCRIBE over the loaded model; results are capped and download as CSV |
| Query from code (Full) | `POST /api/v1/apps/{app-id}/hooks/sparql`, then read `GET /api/v1/apps/{app-id}/hooks/sparql/runs?include_results=true` |

Updates and remote `SERVICE` queries are refused. Request and response shapes are in the [API reference](fdd-data-access.html).
