# Home Assistant and Node-RED integration

Open-FDD exposes an **HA/Node-RED–grade integration layer**: REST API, WebSocket event stream, fault state, jobs, and a guarded BACnet write path. Home Assistant and Node-RED talk only to Open-FDD; they never write directly to BACnet.

## Architecture

```
DDC / BMS → BACnet → Open-FDD (API + graph + FDD) → HA integration / Node-RED
                        ↑                                    ↓
                        └────── POST /bacnet/write_point ────┘
```

- **Read path:** BACnet scrapers (or gateways) push data into Open-FDD; timeseries and fault results are stored and exposed via REST and WebSocket.
- **Write path:** HA or Node-RED call **Open-FDD** `POST /bacnet/write_point`. Open-FDD validates the point, records an audit log, and forwards the write to the BACnet gateway. HA never talks to BACnet directly; Open-FDD enforces constraints and audit.

## Principle

**HA (and Node-RED) never write directly to BACnet.** All writes go through Open-FDD so that:

- Point existence and addressing are validated.
- Optional min/max or TTL can be applied.
- Every write is logged in `bacnet_write_audit` and can emit `bacnet.write.succeeded` / `bacnet.write.failed` events.

## Discovery and API

- **GET /capabilities** — Version and feature flags (`websocket`, `fault_state`, `jobs`, `bacnet_write`). Use for discovery and to decide whether to use WebSocket or polling.
- **GET /faults/active** — Current active fault state (for HA binary_sensors).
- **GET /faults/definitions** — Fault labels (name, severity, category).
- **POST /jobs/fdd/run** — Start an FDD run (returns `job_id`; poll **GET /jobs/{job_id}** or subscribe to `fdd.run.*`).
- **POST /bacnet/write_point** — Write a value to a point (body: `point_id`, `value`, optional `ttl_seconds`, `source`).

Auth: when `OFDD_API_KEY` is set, send `Authorization: Bearer <key>` on all requests except `/health` and `/app`. WebSocket: same key as query param `token` on `/ws/events`.

## Brick Occupancy and HA schedule logic

Points with Brick type indicating occupancy (e.g. `brick:Occupancy_Status`) can be mapped to HA **binary_sensors** for schedule logic:

- **GET /entities/suggested** — Returns suggested HA entity mappings: point id, `suggested_ha_domain` (`binary_sensor` for occupancy), `suggested_ha_id` (e.g. `openfdd_ahu1_occupied`).
- **GET /points** — Includes `brick_type` and `equipment_id`; the integration can create `binary_sensor.openfdd_<equipment>_occupied` for occupancy points.

Example: an AHU with an occupancy point becomes `binary_sensor.openfdd_ahu1_occupied`. HA automations can use this for scheduling (e.g. reduce setpoints when unoccupied).

## Home Assistant Add-on and Integration

Dockerfile-related and HA packaging live under **stack/** with the rest of the stack:

- **Add-on:** `stack/ha_addon/openfdd/` — packages the Open-FDD API so it runs inside Home Assistant. Configure `api_key` and optional `bacnet_server_url` in add-on options. Build with `./scripts/bootstrap.sh --ha-addon` or use HA Supervisor addon build.
- **Integration:** `stack/ha_integration/custom_components/openfdd/` — config flow (URL + API key), coordinator (polling `/faults/active`), and **full API as services**. You can do everything from HA that `scripts/graph_and_crud_test.py` tests: `openfdd.get_health`, `openfdd.get_config` / `openfdd.put_config`, `openfdd.list_sites`, `openfdd.create_site`, `openfdd.get_site`, `openfdd.update_site`, `openfdd.delete_site`, and the same for equipment and points; `openfdd.data_model_serialize`, `openfdd.get_data_model_ttl`, `openfdd.get_data_model_export`, `openfdd.put_data_model_import`, `openfdd.run_sparql`, `openfdd.get_data_model_check`; `openfdd.bacnet_server_hello`, `openfdd.bacnet_whois_range`, `openfdd.bacnet_point_discovery_to_graph`; `openfdd.get_download_csv`, `openfdd.post_download_csv`, `openfdd.get_download_faults`; `openfdd.run_fdd`. Results are fired as events (`openfdd.<service>_result`) so automations can react. If `/capabilities` reports `websocket: true`, the integration can optionally subscribe to `/ws/events` and refresh on `fault.*` and `fdd.run.*` events.

**Version:** Same source as the FastAPI app — **pyproject.toml**. The addon gets it at build time (`./scripts/bootstrap.sh --ha-addon` writes it into config.yaml). The integration gets the Open-FDD version from the API at runtime via GET `/capabilities` (no separate version to sync).

### Home Assistant services

The integration exposes the full Open-FDD API as **services** under the `openfdd` domain. Call them from Developer Tools → Services, or from automations and scripts. Services that return data fire an event `openfdd.<service_name>_result` with payload `{"data": ...}` so you can trigger automations on the result.

| Service | Description | Parameters |
|---------|-------------|------------|
| **Health & config** | | |
| `openfdd.get_health` | API health (status, serialization). | — |
| `openfdd.get_config` | Current platform config (RDF graph). | — |
| `openfdd.put_config` | Update platform config (partial; omitted keys unchanged). | Any config keys (e.g. `rule_interval_hours`, `bacnet_server_url`, `lookback_days`). |
| **Sites** | | |
| `openfdd.list_sites` | List all sites. | — |
| `openfdd.create_site` | Create a site. | `name` (required), `description`, `metadata` |
| `openfdd.get_site` | Get site by ID. | `site_id` |
| `openfdd.update_site` | Update a site. | `site_id`, optional `name`, `description`, `metadata` |
| `openfdd.delete_site` | Delete site (cascade: equipment, points, timeseries, faults). | `site_id` |
| **Equipment** | | |
| `openfdd.list_equipment` | List equipment, optionally by site. | `site_id` (optional) |
| `openfdd.create_equipment` | Create equipment under a site. | `site_id`, `name` (required), optional `description`, `equipment_type`, `feeds_equipment_id`, `fed_by_equipment_id`, `metadata` |
| `openfdd.get_equipment` | Get equipment by ID. | `equipment_id` |
| `openfdd.update_equipment` | Update equipment. | `equipment_id`, optional `name`, `description`, `equipment_type`, `feeds_equipment_id`, `fed_by_equipment_id`, `metadata` |
| `openfdd.delete_equipment` | Delete equipment (cascade: points). | `equipment_id` |
| **Points** | | |
| `openfdd.list_points` | List points, optionally by site or equipment. | `site_id`, `equipment_id` (optional) |
| `openfdd.create_point` | Create a point. | `site_id`, `external_id` (required), optional `brick_type`, `fdd_input`, `unit`, `description`, `equipment_id`, `bacnet_device_id`, `object_identifier`, `object_name`, `polling` |
| `openfdd.get_point` | Get point by ID. | `point_id` |
| `openfdd.update_point` | Update a point. | `point_id`, optional fields as in create |
| `openfdd.delete_point` | Delete point (cascade: timeseries). | `point_id` |
| **Data model** | | |
| `openfdd.data_model_serialize` | Serialize in-memory graph to TTL file. | — |
| `openfdd.get_data_model_ttl` | Get full data model TTL (Brick + BACnet). | `site_id`, `save` (optional, default true) |
| `openfdd.get_data_model_export` | Export points (BACnet + DB) for LLM tagging. | `site_id`, `bacnet_only` (optional) |
| `openfdd.put_data_model_import` | Import Brick mapping (create/update points, optional equipment). | `points` (required), `equipment` (optional) |
| `openfdd.run_sparql` | Run a SPARQL query against the data model. | `query` (required) |
| `openfdd.get_data_model_check` | Data model integrity check (triple counts, orphans). | — |
| **BACnet** | | |
| `openfdd.bacnet_server_hello` | Test BACnet gateway reachability. | `url` (optional) |
| `openfdd.bacnet_whois_range` | Discover BACnet devices in instance range. | `start_instance`, `end_instance`, optional `url`, `gateway` |
| `openfdd.bacnet_point_discovery_to_graph` | Run point discovery for a device and merge into graph. | `device_instance` (required), optional `update_graph`, `write_file`, `url`, `gateway` |
| **Download** | | |
| `openfdd.get_download_csv` | Download timeseries as CSV (GET style). | `site_id`, `start_date`, `end_date`, `format` (optional: wide/long) |
| `openfdd.post_download_csv` | Download timeseries as CSV with point filter. | `site_id`, `start_date`, `end_date`, optional `format`, `point_ids` |
| `openfdd.get_download_faults` | Export fault results (JSON or CSV). | `start_date`, `end_date`, optional `site_id`, `format` (json/csv) |
| **Job** | | |
| `openfdd.run_fdd` | Trigger an FDD rule run now. | — |

All services use the first Open-FDD config entry (base URL + API key). Results for get/list/export-style services are published as events so automations can subscribe (e.g. `openfdd.list_sites_result`, `openfdd.get_data_model_export_result`).

### Node-RED

The same API works with **Node-RED**: use a config node for base URL and API key, subscribe to `ws://host:8000/ws/events?token=API_KEY` for events (`fault.*`, `crud.point.*`, `fdd.run.*`), and call REST with `Authorization: Bearer <key>` (e.g. run FDD, write point). Planned contrib nodes: **openfdd-server** (config), **openfdd-events** (WebSocket), **openfdd-api** (REST).
