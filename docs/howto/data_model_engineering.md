# Data Model Engineering (MVP)

Open-FDD keeps Brick as the operational model and adds an Engineering layer as metadata plus RDF extensions.

## What this adds

- New frontend page: `Data Model Engineering`
- Equipment engineering metadata persisted in `equipment.metadata.engineering`
- Round-trip support via `PUT /data-model/import` and `GET /data-model/export`
- RDF emission with:
  - `ofdd:*` engineering extension predicates for practical fields
  - `s223:*` topology concepts for connection points and conduits
- New Data Model Testing engineering query presets

## Backward compatibility

- Existing Brick/BACnet/time-series/rule-input workflows are unchanged
- Unknown metadata keys are preserved on import
- Existing JSON import/export shape still works; engineering fields are optional

## JSON pattern

Use `equipment[].engineering` in import payloads. Example in:

- `examples/engineering/engineering_import_example.json`

## RDF pattern

Generated RDF keeps Brick relationships and appends engineering predicates. Example in:

- `examples/engineering/engineering_topology_example.ttl`

## Query examples

See:

- `examples/engineering/sparql_engineering_examples.md`
