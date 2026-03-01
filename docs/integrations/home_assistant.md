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

### Get your Open-FDD API key

**Secure-by-default:** When you run `./scripts/bootstrap.sh` (without `--no-auth`), the script generates a random API key and writes it to **`stack/.env`** as `OFDD_API_KEY=...`. It prints the key and tells you to paste it into the Home Assistant Open-FDD integration. Use that value when adding the integration (Settings → Devices & services → Add integration → Open-FDD). The integration’s API key field is **optional**: leave it blank if the server does not require auth; if the server returns 401/403, the form will ask for the key (paste from `stack/.env`).

- **Where to find the key (Docker stack):** In the repo, open **`stack/.env`** and look for the line `OFDD_API_KEY=...`. Copy the value after the `=`. If the file doesn’t exist or has no `OFDD_API_KEY`, run `./scripts/bootstrap.sh` once (it will generate and append it), or generate one yourself (see below) and add `OFDD_API_KEY=<key>` to `stack/.env`.
- **Generate a key yourself:** From a terminal: `openssl rand -hex 32`. Add that value to `stack/.env` as `OFDD_API_KEY=<paste-here>` and restart the API container so it picks up the env.
- **HA addon:** In the addon’s configuration (Settings → Add-ons → Open-FDD → Configuration), set **api_key** to the same secret (e.g. the value from `stack/.env` or a new `openssl rand -hex 32`). The addon exports it as `OFDD_API_KEY` internally.
- **Recommendation:** If the Open-FDD API is reachable on your LAN (e.g. `http://192.168.x.x:8000`), enable auth by ensuring `OFDD_API_KEY` is set (bootstrap does this by default). Use `--no-auth` only for local-only or test setups where you explicitly do not want Bearer auth.

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

### Replicating the CRUD/graph test from Home Assistant

The script **`scripts/graph_and_crud_test.py`** is an end-to-end test that hits the Open-FDD API: health, config (GET/PUT), sites/equipment/points CRUD, data-model (serialize, TTL, export, import, SPARQL), BACnet proxy (server_hello, whois_range, point_discovery_to_graph), and download endpoints. You can run the same flows from HA without fat-fingering the GUI by using **Developer Tools → Services**.

1. **Configure the integration**  
   Add the Open-FDD integration (Settings → Devices & services → Add integration → Open-FDD). Set the base URL (e.g. `http://localhost:8000` if Open-FDD runs on the same host, or the addon URL) and API key if you set one.

2. **Call services**  
   Go to **Developer Tools → Services**. Choose a service, e.g. `openfdd.get_health`, leave parameters empty, and call it. Check the result in the notification or in **Developer Tools → Events** (listen for `openfdd.get_health_result`). Minimal “smoke” sequence that mirrors the script:
   - `openfdd.get_health`
   - `openfdd.get_config` then optionally `openfdd.put_config` with a small change
   - `openfdd.list_sites`
   - `openfdd.data_model_serialize`
   - `openfdd.run_sparql` with e.g. `query`: `PREFIX brick: <https://brickschema.org/schema/Brick#> SELECT ?s ?l WHERE { ?s a brick:Site . ?s <http://www.w3.org/2000/01/rdf-schema#label> ?l }`
   - `openfdd.get_data_model_export` (use `site_id` if you have one)
   - For BACnet: `openfdd.bacnet_server_hello`, `openfdd.bacnet_whois_range`, `openfdd.bacnet_point_discovery_to_graph` (with `device_instance` and optional `url`).

3. **Results**  
   Each call that returns data fires an event `openfdd.<service_name>_result` with `data` in the payload; you can use that in automations or just read the service call response in Developer Tools.

### Addon image and local install (e.g. same Linux host)

The addon is built as a **Docker image** `openfdd-addon:local` (no PyPI; open-fdd is installed from the repo at build time).

- **Build the addon image** (from the open-fdd repo root):
  ```bash
  ./scripts/bootstrap.sh --ha-addon
  ```
  This builds the image `openfdd-addon:local` and exits (it does not start the full Docker stack).

- **Install in Home Assistant**
  - Copy the addon folder into your HA addons directory: copy **`stack/ha_addon`** (the folder that contains the `openfdd` addon) to wherever your Home Assistant expects addons (e.g. for **Home Assistant Supervised** on Linux: often `~/homeassistant/addons` or a path you configured for local addons).
  - Ensure the addon uses the image **`openfdd-addon:local`**. How you set that depends on your HA setup: with Supervisor, if the addon is loaded from a local path, you may need to set the addon’s image to `openfdd-addon:local` in the addon configuration (or in the addon’s `config.yaml` if your setup supports an `image` key so Supervisor uses the pre-built image instead of building from the Dockerfile).
  - In HA: **Settings → Add-ons → Add-on store** (or **Local add-ons**), add the Open-FDD addon if it isn’t listed, then start it. Set `api_key` and optional `bacnet_server_url` in the addon options.

- **Run Home Assistant on the same Linux Mint machine**
  - **With addons (recommended if you want the addon):** Use **Home Assistant Supervised** on your Linux Mint host. Install Docker and the Supervisor stack; then add the Open-FDD addon as above and use the image `openfdd-addon:local`.
  - **Without addons:** Run **Home Assistant Container** (Docker) and run the full Open-FDD stack separately (e.g. `./scripts/bootstrap.sh` in the open-fdd repo). Point the Open-FDD integration in HA to the Open-FDD API URL (e.g. `http://<host>:8000`). No addon needed; the integration talks to the API over the network.

### Node-RED

The same API works with **Node-RED**: use a config node for base URL and API key, subscribe to `ws://host:8000/ws/events?token=API_KEY` for events (`fault.*`, `crud.point.*`, `fdd.run.*`), and call REST with `Authorization: Bearer <key>` (e.g. run FDD, write point). Planned contrib nodes: **openfdd-server** (config), **openfdd-events** (WebSocket), **openfdd-api** (REST).
