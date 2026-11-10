---
title: Modeling
nav_order: 3
---

# Model equipment and points

Open-FDD discovers sites, equipment, and points from NF's Haystack model. No site-specific code or app settings are
needed. Tag the model in NF, then reload the app.

## Records and attributes

| Record | Useful fields |
|---|---|
| Site | latitude, longitude, timezone, optional area and areaUnit |
| Equipment | siteRef, equipment markers such as ahu, vav, or chiller |
| Point | siteRef, equipRef, class, markers, kind, unit, and history |

Trend points used by a chart or rule. Site coordinates support the weather hook. If using energy intensity charts,
set floor area and its unit.

## How a role binds

Rules and charts ask for named roles such as supply-air temperature or fan command. The generated
[FDD catalog](fdd-rules.html) lists each rule's roles; the NF class and marker map is in
nf-app/static/fdd-catalog.json.

A point fills a role when its NF class matches a listed class, or when it has every marker for the role. A class is
preferred because it is more specific. Markers are one comma-separated string in NF; setting class does not add
markers. Equipment kinds come from equipment markers. Weather points fill weather roles only.

The FDD and RCx pages show missing required roles. Add the appropriate class or markers to the point in NF, ensure it
has history and a usable unit, then reload.

## Units and checks

Use truthful point units. Open-FDD converts supported values to SI at ingest; rules never infer a unit from magnitude.
Unknown or incompatible units are skipped. See [Units](units.html).

Useful checks: Model and RDF views report dangling references; the FDD tab reports missing rule inputs. For RDF
export and query examples, see [RDF and SPARQL](rdf-sparql.html). Internal details about NF layers and marker queries
remain in the repository's docs/operations/nf/haystack-tagging.md.
