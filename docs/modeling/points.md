---
title: Points
parent: Data modeling
nav_order: 4
---

# Points

Points are time-series references in the Open-FDD data model. They link raw telemetry (BACnet objects, weather sensors) to equipment and Brick semantics.

---

## Structure

Each point has:

| Field | Description |
|-------|-------------|
| `id` | UUID primary key |
| `site_id` | FK to sites |
| `equipment_id` | FK to equipment (nullable) |
| `external_id` | Raw identifier from source (e.g. BACnet object name); unique per site |
| `fdd_input` | Column name used by FDD rules (e.g. `oat`, `sat`); data-model API uses `rule_input` |
| `brick_type` | Optional Brick class (e.g. `Outside_Air_Temperature_Sensor`) |
| `unit` | Optional unit of measure |
| `description` | Optional |
| **BACnet addressing** | |
| `bacnet_device_id` | Optional. BACnet device instance (e.g. `3456789`). With `object_identifier`, used by the BACnet scraper to poll this point. |
| `object_identifier` | Optional. BACnet object ID (e.g. `analog-input,1`). |
| `object_name` | Optional. BACnet object name (often same as `external_id`). |
| **Modbus TCP** | |
| `modbus_config` | Optional JSON object describing **one** register read per point (flat shape: `host`, `port`, `unit_id`, `timeout`, `address`, `count`, `function`, optional `decode`, `scale`, `offset`, `label`). Decodes **`float32`**, **`uint32`**, and **`int32`** require **`count` ≥ 2** (two 16-bit registers). The Open-FDD API **`POST /bacnet/modbus_read_registers`** accepts a **batch** body with `registers: [...]` for the gateway test bench; that is **not** the same as persisting multiple registers in one `modbus_config`. For persistence, either use the flat fields, or a single-element `registers` array (the server merges it)—use one point row per register when you have several. On **`PUT /data-model/import`**, omit `modbus_config` to leave the column unchanged; set it to JSON **`null`** or **`{}`** to clear. Serialized in Brick TTL as `ofdd:modbusConfig` (JSON string). Same scrape enable flag and interval as BACnet (`OFDD_BACNET_SCRAPE_ENABLED`, `bacnet_scrape_interval_min` / API config). |

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

- **BACnet layer:** Points that have `bacnet_device_id` and `object_identifier` are scraped by the BACnet driver (data-model path). Add them via CRUD or after **POST /bacnet/point_discovery_to_graph** and data-model export/import. `external_id` is typically the BACnet object name.
- **Modbus layer:** Points with `modbus_config` set are read in the same scrape loop (after BACnet), using the configured gateway URL. Add them via **POST /points**, the **Modbus client** tab on **BACnet tools**, or **PUT /data-model/import** with `modbus_config` (requires `site_id`/`site_name`, `external_id`, and a valid config: at least `host` and numeric `address`). Do not paste a multi-register **`registers`** array from the proxy request into one point—create one point per register (the UI does this when you name each row). Useful for a small set of utility or meter registers on typical BAS jobs.
- **Weather layer:** Points with `external_id` = `temp_f`, `rh_pct`, `dewpoint_f`, etc. come from the Open-Meteo weather fetch. They are linked to a synthetic equipment **Open-Meteo** (type **Weather_Service**) per site so they appear under “Open-Meteo” (web weather) in the **Data model** and **Points** tree. In the RDF graph that equipment is tagged with `ofdd:dataSource "open_meteo"` so you can query it via SPARQL.
- **Rule layer:** `fdd_input` / `rule_input` maps to DataFrame column names used by YAML rules.

The data-model API and Brick TTL coordinate `external_id` ↔ `rule_input` ↔ `brick_type`.
Open-FDD also emits Brick v1.4 external references (`ref:hasExternalReference`) so points can be resolved to BACnet and timeseries systems. See [External representations](external_representations).

### BACnet addressing

Points with `bacnet_device_id` and `object_identifier` set are used by the BACnet scraper (data-model path). Add them via CRUD or after point_discovery_to_graph and data-model export/import. See [BACnet overview](../bacnet/overview#discovery-and-getting-points-into-the-data-model).

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
