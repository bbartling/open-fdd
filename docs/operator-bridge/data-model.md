# Data Model — FDD query presets

The **SPARQL** tab includes **FDD / BRICK query presets** — composed queries across
`model.json`, rule bindings, and BACnet metadata:

- Rules → Equipment / Sensors / BACnet devices
- Equipment → Points, AHUs/VAVs/Zones
- Missing rule bindings, orphan points, sensor classes, coverage by equipment type

API: `GET /api/model/fdd-query-presets`, `GET /api/model/fdd-query-presets/{id}`.
