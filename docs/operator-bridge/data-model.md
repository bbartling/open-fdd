# Data Model — sync and FDD queries

## Explorer (BACnet poll sync)

The **Explorer** tab focuses on **BACnet poll CSV ↔ model.json** sync status and
**Sync poll → model**. Write TTL lives under **Advanced** (or SPARQL RDF tools).

## FDD query presets

The **SPARQL** tab includes **FDD / BRICK query presets** — composed queries across
`model.json`, rule bindings, and BACnet metadata:

- Rules → Equipment / Sensors / BACnet devices
- Equipment → Points, AHUs/VAVs/Zones
- Missing rule bindings, orphan points, sensor classes, coverage by equipment type

API: `GET /api/model/fdd-query-presets`, `GET /api/model/fdd-query-presets/{id}`.
