# Drivers, historian, and FDD

Rust-only layout: driver code in `edge/src/drivers/`, fault detection in `edge/src/fdd/`.

See [architecture overview](overview.md) for the full platform picture (Arrow/Feather historian, DataFusion FDD, Docker services).

## Driver tree vs REST APIs

The React **Driver Tree** sidebar reads `workspace/data/drivers/bacnet/driver_tree.json`. It is meant to list all four protocol families:

| Driver ID | Label | Tree content | Primary API |
| --- | --- | --- | --- |
| `bacnet-ip` | BACnet/IP | Devices, points, override scan | `/api/bacnet/*` |
| `modbus-tcp` | Modbus/TCP | Units, registers | `/api/modbus/*` |
| `json-api` | JSON API | HTTP sources | `/api/json-api/*` |
| `haystack` | Haystack Gateway | Sites + integration note | `/api/haystack/*`, `/api/model/haystack` |

If the on-disk driver tree was narrowed to BACnet-only (common after bench commissioning), Modbus, JSON API, and Haystack disappear from the sidebar even though their APIs remain live on the bridge. Merge the other driver blocks back into the JSON file, or remove the file to fall back to the built-in default tree in `edge/src/drivers/bacnet.rs`.

## Driver modules

```text
edge/src/drivers/
  bacnet.rs       Who-Is, driver tree, ReadProperty, override scan
  modbus.rs       Modbus/TCP scan/read
  json_api.rs     JSON API sources and poll-once
  haystack.rs     Haystack read/nav/ops facade
```

Each driver exposes honest **simulated** vs **live** mode via environment variables (`OPENFDD_BACNET_MODE`, `OPENFDD_MODBUS_MODE`, etc.).

## Semantic model

```text
edge/src/model/
  assignments.rs   Haystack-centric point and rule bindings
```

Driver points map to Haystack refs. FDD rules and algorithms bind to Haystack IDs — not directly to BACnet or Modbus addresses.

```text
Field bus (BACnet / Modbus / JSON / Haystack)
  → driver tree + discovery
  → Haystack model points
  → Arrow historian RecordBatches
  → DataFusion SQL rules
  → fault state + reports
  → React UI
```

## Historian (Apache Arrow)

```text
edge/src/historian/
  arrow_table.rs   Telemetry schema for RecordBatches
```

Normalized long-format columns include `timestamp`, `equipment_id`, `fdd_input`, `value`, `quality`, `source`, `is_simulated`. Rules typically query a pivoted `telemetry_pivot` view.

## FDD (DataFusion SQL)

```text
edge/src/fdd/
  sql_safety.rs     Blocks DDL/DML in rule SQL
  execution.rs      DataFusion engine over Arrow tables
  wires/            Rule graph, assignments, activation RBAC
```

Production path:

```text
driver samples → Arrow batches → DataFusion SELECT → confirmation → fault outputs
```

No Python, PyArrow, or pandas in the edge runtime.

## Related docs

- [Assignment model](../ASSIGNMENT_MODEL.md)
- [Verification: BACnet](../verification/bacnet-overrides.md)
- [Verification: Modbus](../verification/modbus-live.md)
