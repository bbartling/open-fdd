# Drivers, historian, and FDD

Rust-only layout: driver code in `edge/src/drivers/`, fault detection in `edge/src/fdd/`.

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
