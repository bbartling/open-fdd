---
title: Driver framework
nav_order: 5
has_children: true
---

# Driver framework

Open-FDD edge commissioning uses a **shared driver pattern** for OT data sources. Each driver polls field devices on a schedule, stores long-format samples in workspace CSVs, and ingests into the **feather historian** under a distinct `source` tag for FDD and plots.

## Drivers

| Driver | Protocol | Feather `source` | Commissioning tab |
|--------|----------|------------------|-------------------|
| [BACnet](../bacnet/index) | MS/TP / IP (`:47808`) | `bacnet` | BACnet |
| Modbus | Modbus TCP | `modbus` | Modbus |
| [JSON API](json-api) | HTTP/HTTPS REST (+ [OpenWeather showcase](json-api#openweathermap-showcase-recommended-demo)) | `json_api` | JSON API |

All three drivers share the same operator workflow:

1. **Discover or configure** — add devices/endpoints to the driver registry.
2. **Request once** — on-demand read to verify connectivity and JSON path / register map.
3. **Request & store** — append to poll CSV and write a feather shard.
4. **Enable polling** — 1 / 5 / 10 / 15 minute intervals via tree right-click or bulk toolbar.
5. **Poll all now** — force one worker cycle without waiting for the interval.

## Data layout

```
workspace/
  bacnet/commissioning/   points.csv, discovered inventory
  bacnet/polls/           samples.csv
  modbus/commissioning/   registers.csv
  modbus/polls/           samples.csv
  json_api/commissioning/ endpoints.csv
  json_api/polls/         samples.csv
  data/feather_store/
    bacnet/{site_id}/     shard-*.feather
    modbus/{site_id}/
    json_api/{site_id}/
```

## Historian and FDD

- **Plot tab** — numeric columns from `bacnet` and `modbus` sources (`GET /api/timeseries/plot?source=…`).
- **String JSON fields** — stored in feather under `json_api`; use the JSON API tree or feather directly (plot is numeric-only).
- **FDD batch** — merges `bacnet` + `modbus` + `json_api` historian columns by nearest timestamp; rules use BRICK-bound `external_id` names (e.g. compare BACnet `oa-t` vs JSON API `web-oat-t` — see [JSON API](json-api)).
- **BRICK model** — bind points in **Model & assignments** commissioning JSON; sync TTL for SPARQL scope.

## Rule Lab (Arrow upload/download)

1. **Download kit** — zip with `rule.py` (constants at top), `data.py`, `sample.feather` (~3h), `run_test.py`, `requirements.txt`.
2. Local test: `pip install -r requirements.txt` then edit constants in `rule.py` and `python run_test.py`.
3. **Upload rule.py** — Arrow-only; must define `apply_faults_arrow(table, cfg, context=None)`.
4. Browser shows **read-only** source; use Quick test + Update all records.

API: `GET /api/rules/export-kit`, `POST /api/rules/upload`.

## Smoke validation

From repo root on a running stack (`http://127.0.0.1:8765`):

```bash
python3 scripts/smoke_multi_driver_stack.py
python3 scripts/validate_modbus_temp_e2e.py --no-server
```

## Related docs

- [Data flow](../architecture/data-flow) — poll → CSV → feather → FDD
- [API routes](../appendix/bridge_api) — REST reference
- [BACnet polling](../bacnet/polling) — commission container loop
