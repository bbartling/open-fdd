---
title: Haystack tagging
parent: NF operations
nav_order: 4
---

# Haystack tagging in NF: the operator view

[Modeling](../../modeling.html) says **what** Open-FDD needs tagged. This page is how NF stores those tags and how
to query them, so you can check a site from a terminal. The apps and the tools in
[`scripts/nf/tools/`](https://github.com/bbartling/open-fdd/tree/master/scripts/nf/tools) find everything by tag;
nothing is looked up by a name, uuid or address. To support a new site, tag it in NF.

## Layers

NF keeps one record per point **per layer**:

| Layer | What it holds |
|---|---|
| `hpl:bacnet:<n>` (and other protocol layers) | what the driver discovered: device and object ids, name, units |
| `model` | your Haystack tags: `siteRef`, `deviceRef`, `equipRef`, `class`, `markers`, `kind`, `unit`, `dis`; also the SITE, EQUIPMENT and DEVICE records themselves |
| `default` | the merged view (protocol + model) plus the latest value; **query this for points** |

Model records have a `pointType` of `SITE`, `EQUIPMENT` or `DEVICE`. Their `attrs.id` is what other records point at
with `siteRef` / `equipRef` / `deviceRef`.

## Tags on a point

| Attr | Meaning |
|---|---|
| `siteRef`, `equipRef`, `deviceRef` | ids of the site, equipment and BACnet device records (a weather point carries `weatherStationRef` instead of `equipRef`) |
| `class` | NF equipment/point class in dash-case, for example `zone-air-temp-sensor`; the list is `GET /api/v1/equipment/classes?pageSize=1000` |
| `markers` | **one comma-separated string** (`discharge,air,temp,sensor`) |
| `kind`, `unit` | `Number` or `Bool`, and the unit (`degF`, `cfm`, `inH2O`) |
| `dis` | the display name shown to people |

Points need an explicit `markers` attr: **setting `class` does not add markers to a point** (equipment markers do
follow the equipment class). Anything that queries by marker, including the tools here, needs them set.

## Query by tag

`POST /api/v1/point/query` with a `structuredQuery`. **One marker per clause**, combined with `and`:

```json
{
  "layer": "default",
  "pageSize": 500,
  "structuredQuery": { "and": [
    { "field": { "property": "siteRef", "text": "<site-id>" } },
    { "field": { "property": "markers", "text": "point" } },
    { "field": { "property": "markers", "text": "temp" } }
  ] }
}
```

Use `layer: "model"` for the SITE / EQUIPMENT / DEVICE records. Page with `nextPageToken`. Selecting points to
change (`point/copy`, quality rules) from a tag query needs `indexLayer: "default"`, not the protocol layer.

Try it without writing any JSON:

```bash
python3 scripts/nf/tools/nf_portal_sensors.py lan --env ~/.secrets/nf_api.env --tags discharge,air,temp
```

## Tips

- Prefer a `class` over bare markers; bind rules and charts by class first (see [Modeling](../../modeling.html)).
- Imported BACnet points **do not poll until a period is set**. After a scan and import, set a poll period or you
  will see model records with no values.
- Trend (history) every point a chart or rule uses.
- Tag spare I/O `spare`, and non-standard tags are fine, but the RDF export defines each one as a `ph:marker`
  ([RDF and SPARQL](../../rdf-sparql.html)).
- A bare controller with no ontology class of its own: model it as `controller` (or the unit it really is).
- Brick is **either/or** in NF: enabling the Brick ontology changes the model layer, it is not a second tag set in
  parallel. Open-FDD uses Haystack.
- The first tag write on a freshly imported point is uuid-driven (the NF MCP `tag_points`, or the console's
  Object Explorer). After that, selection can be by tag.
- Never repair a damaged point by passing its uuid to `POST /api/v1/bacnet/local`; see [NF gotchas](nf-gotchas.html).
- Start a modeling session (`session start` in the NF MCP) before bulk tag writes so there is an undo log.
- Check the result in the app: the FDD tab lists missing roles, and Model and RDF flags dangling refs.
