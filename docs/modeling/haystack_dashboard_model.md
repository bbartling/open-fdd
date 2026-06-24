# Haystack dashboard model layer

The generic model query layer (`edge/src/model/query.rs`) powers dashboard analytics without hardcoded sites or SPARQL.

## Capabilities

- List sites, buildings, equips, points
- Group points by equip; group equips by type
- Count mapped vs unmapped points
- Source coverage by protocol (BACnet, Modbus, JSON API tags)
- Future RDF/SPARQL adapter hook (optional)

## Data sources

1. Haystack fixture/model JSON (`/api/model/haystack`)
2. Open-FDD assignment layer (`/api/model/assignments`)
3. Historian pivot rows for live fault evaluation
4. Imported point mappings and source registry metadata

## Example

```bash
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/dashboard/model-coverage
```

Returns `equipment_count`, `point_count`, `mapped_points`, `unmapped_points`, and `model_score`.
