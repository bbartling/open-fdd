# Drivers and FDD Layout

This Rust-only layout keeps driver code in `edge/src/drivers/` and FDD code in `edge/src/fdd/`.

## Driver modules

```text
edge/src/drivers/
  mod.rs
  bacnet.rs      Who-Is, point registry, driver tree, ReadProperty, override scan facade
  modbus.rs      Modbus/TCP scan/read facade for rusty-modbus path
  json_api.rs    JSON API source registration and poll-once facade
  haystack.rs    Project Haystack about/ops/read/nav facade
```

## Data model

```text
edge/src/model/
  mod.rs         Haystack is the semantic model surface
```

Niagara-style integration is intentionally represented through Project Haystack:

```text
Niagara/BAS server
→ Haystack read/nav/ops
→ Rust Haystack gateway
→ Open-FDD model rows
→ Arrow historian rows
→ DataFusion SQL fault detection
```

## Historian / Arrow

```text
edge/src/historian/
  arrow_table.rs Arrow-shaped HVAC rows and historian query facade
```

The prototype serves JSON with the same schema intended for Arrow RecordBatches:

```text
ts, equip, sat, sat_sp, duct_static, duct_static_sp, oat, fan_cmd
```

## FDD

```text
edge/src/fdd/
  datafusion_sql.rs DataFusion SQL rule strings, rule save facade, batch result facade
```

The baseline FDD rule path is:

```text
driver samples
→ Arrow-shaped historian table
→ DataFusion SQL
→ fault results
→ API + React UI
```

No Python, no PyArrow, no pandas.
