---
title: Points
parent: Data modeling
nav_order: 4
---

# Points

Points are time-series references in the Open-FDD data model. They link **telemetry that already arrived in SQL** (historian / ETL keyed by `external_id`) to equipment and Brick semantics. **Open-FDD does not poll BACnet or Modbus**; site **VOLTTRON** does.

---

## Structure

Each point has:

| Field | Description |
|-------|-------------|
| `id` | UUID primary key |
| `site_id` | FK to sites |
| `equipment_id` | FK to equipment (nullable) |
| `external_id` | Raw identifier from the **writer** (e.g. VOLTTRON historian topic / device path); unique per site |
| `fdd_input` | Column name used by FDD rules (e.g. `oat`, `sat`); data-model API uses `rule_input` |
| `brick_type` | Optional Brick class (e.g. `Outside_Air_Temperature_Sensor`) |
| `unit` | Optional unit of measure |
| `description` | Optional |
| **Optional legacy metadata** | |
| `bacnet_device_id` | Optional. May be filled from **imports** or historical tooling; **not** used by Open-FDD to poll BACnet. |
| `object_identifier` | Optional. Same — metadata only in the default architecture. |
| `object_name` | Optional. Human-readable name (often aligns with `external_id`). |
| `modbus_config` | Optional. **Legacy / lab** column; **ingest Modbus in VOLTTRON**, then map SQL rows to `external_id`. |

---

## Time-series data

Readings are stored in `timeseries_readings`:

| Column | Type | Description |
|--------|------|-------------|
| `point_id` | UUID | FK to points |
| `ts` | timestamp | Timestamp (UTC) |
| `value` | float | Numeric value |

TimescaleDB hypertable, optimized for range scans and downsampling.

---

## Layers and mapping

- **VOLTTRON / SQL layer (default):** Writers (historian, agents) insert rows into `timeseries_readings` keyed by `point_id` / `external_id`. Define points in CRUD or import so **`external_id`** matches what VOLTTRON publishes. Use **`openfdd_stack.volttron_bridge`**. See **[Site VOLTTRON and the data plane (ZMQ)](../concepts/site_volttron_data_plane)**.
- **Weather layer:** Points with `external_id` = `temp_f`, `rh_pct`, `dewpoint_f`, etc. come from the Open-Meteo weather fetch when enabled. They are linked to synthetic equipment **Open-Meteo** (type **Weather_Service**) per site. RDF marks `ofdd:dataSource "open_meteo"`.
- **Rule layer:** `fdd_input` / `rule_input` maps to DataFrame column names used by YAML rules.

The data-model API and Brick TTL coordinate `external_id` ↔ `rule_input` ↔ `brick_type`.
Open-FDD may emit Brick external references for interoperability; **BACnet/Modbus on the wire remain in VOLTTRON**. See [External representations](external_representations).

### Optional BACnet-style metadata

`bacnet_device_id` / `object_identifier` may still be populated for **imports, migration, or SPARQL examples**. They do **not** cause Open-FDD to poll BACnet in the default deployment. See **[Edge field buses (VOLTTRON)](../bacnet/)**.

---

## API

- `GET /points` — List points (filter by site or equipment)
- `GET /points/{id}` — Get one
- `POST /points` — Create
- `PATCH /points/{id}` — Update
- `DELETE /points/{id}` — Delete (cascades to timeseries_readings; see [Danger zone](../howto/danger_zone))

---

## Queries

```sql
SELECT ts, p.external_id, tr.value
FROM timeseries_readings tr
JOIN points p ON p.id = tr.point_id
WHERE p.external_id = 'temp_f'
  AND ts > NOW() - INTERVAL '1 day'
ORDER BY ts DESC;
```
