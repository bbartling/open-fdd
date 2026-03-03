# Home Assistant and Node-RED integration

Open-FDD exposes an **HA/Node-RED–grade integration layer**: REST API, WebSocket event stream, fault state, jobs, and a guarded BACnet write path. Home Assistant and Node-RED talk only to Open-FDD; they never write directly to BACnet.

---

## Quick setup: Open-FDD + Home Assistant on one Linux machine

This section is a **copy-paste-ready guide** for a beginner on a fresh Linux box. By the end you will have the Open-FDD Docker stack running, Home Assistant running in Docker on the same machine, the Open-FDD custom integration installed and configured, and validation commands to confirm everything works.

**Paths used in examples (change if yours differ):**

| What | Path |
|------|------|
| Open-FDD repo | `/home/ben/open-fdd` |
| Home Assistant config | `/home/ben/homeassistant/config` (created in Step 3; no HA repo clone) |

---

### Step 1: Run the Open-FDD stack

```bash
cd /home/ben/open-fdd
./scripts/bootstrap.sh
```

Wait until the script finishes. It builds and starts the full stack (API, DB, Grafana, BACnet server, etc.). The API will be at **http://localhost:8000**.

**Using the HA addon (Home Assistant OS / Supervised)?** To build the addon image as well, run bootstrap twice:

```bash
./scripts/bootstrap.sh && ./scripts/bootstrap.sh --ha-addon
```

The first run starts the stack; the second builds the addon image `openfdd-addon:local` and prints the API key again. Then copy `stack/ha_addon` to your HA addons folder and set the addon image in config. See [Home Assistant Add-on and Integration](#home-assistant-add-on-and-integration) below for details.

---

### Step 2: Get your API key

Open-FDD **does not generate keys for you** in the UI. When you run bootstrap **without** `--no-auth`, the script **creates a key**, writes it to **`stack/.env`**, and **prints it** in the terminal. Look for:

- `Generated OFDD_API_KEY=...` or  
- `Paste this into the addon's api_key option (and into the HA integration if needed):` followed by the key (when using `--ha-addon`).

You can copy the key from that output. To read it again later:

```bash
grep '^OFDD_API_KEY=' /home/ben/open-fdd/stack/.env
```

Copy the value after the `=`. If there is no line or the file is missing, run bootstrap once (it will generate and append one), or create a key yourself:

```bash
openssl rand -hex 32
```

Then add to `/home/ben/open-fdd/stack/.env`:

```bash
echo "OFDD_API_KEY=<paste-the-key-here>" >> /home/ben/open-fdd/stack/.env
```

Restart the API so it picks up the key:

```bash
cd /home/ben/open-fdd && docker compose -f stack/docker-compose.yml restart api
```

**Test auth (optional but recommended):**

```bash
# Without key → 401 Unauthorized
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/capabilities

# With key → 200 and JSON with version/features
curl -s -H "Authorization: Bearer YOUR_KEY_HERE" http://localhost:8000/capabilities
```

Use the same key when configuring the HA integration (base URL **http://localhost:8000** and API key).

---

### Step 3: Run Home Assistant in Docker

You do **not** clone Home Assistant. You run the official image and a config directory on your machine.

Create the HA config folder (any path you like; this is where HA stores config and where we’ll copy the integration):

```bash
mkdir -p /home/ben/homeassistant/config
```

Run Home Assistant **Container** with `--network=host` so it can reach `localhost:8000`:

```bash
docker run -d \
  --name homeassistant \
  --restart=unless-stopped \
  --network=host \
  -v /home/ben/homeassistant/config:/config \
  ghcr.io/home-assistant/home-assistant:stable
```

**Important:** Paste the whole block as **one command** (one line with backslashes, or multiple lines as shown). If you paste line by line, the shell may treat `-v` as a separate command and you’ll see **`-v: command not found`**.

Wait a minute or two, then open **http://localhost:8123**. Complete the HA onboarding (create account, name, etc.) if it’s a fresh install.

---

### Step 4: Install the Open-FDD custom integration

You need to get the integration files into HA’s `custom_components` folder once. Use the **bootstrap script** (no manual path to remember) or copy by hand.

**Option A — Bootstrap (recommended):** From the open-fdd repo root, pass your HA config directory once:

```bash
./scripts/bootstrap.sh --ha-install-integration /home/ben/homeassistant/config
```

(If your HA config lives elsewhere, use that path. You can set `export OFDD_HA_CONFIG=/path/to/your/ha/config` and then run `./scripts/bootstrap.sh --ha-install-integration` so you don’t type the path each time.)

This copies the integration into `config/custom_components/openfdd` and restarts the `homeassistant` container. To also build the addon image: `./scripts/bootstrap.sh --ha-addon --ha-install-integration /home/ben/homeassistant/config`.

**Option B — Manual copy:** If you prefer not to use the script, copy the integration and restart HA yourself:

```bash
sudo mkdir -p /home/ben/homeassistant/config/custom_components
sudo cp -r /home/ben/open-fdd/stack/ha_integration/custom_components/openfdd /home/ben/homeassistant/config/custom_components/
sudo chown -R $(whoami):$(whoami) /home/ben/homeassistant/config/custom_components
docker restart homeassistant
```

If you get **Permission denied** creating files under `config/`, the `config` directory may be owned by root (e.g. after the first `docker run`). The `sudo` and `chown` above fix that so HA can read the integration.

**Why do I have to install the integration?** Open-FDD is a **custom** integration (not part of Home Assistant Core). It has to be installed once by copying into `custom_components` or via [HACS](https://hacs.xyz/) if you add the repo there. After that, you add the integration in Settings → Devices & services like any other.

---

### Step 5: Configure the integration in Home Assistant

1. Open **http://localhost:8123**.
2. Go to **Settings → Devices & services**.
3. Click **Add integration**, search for **Open-FDD**, select it.
4. Enter:
   - **URL:** `http://localhost:8000` (same machine, so localhost is correct).
   - **API key:** Paste the value from `grep '^OFDD_API_KEY=' /home/ben/open-fdd/stack/.env` (the part after `=`).
5. Submit. You should see **“Success”** and the integration card.

If setup fails with **“Failed to set up: check logs”**, the API is likely returning 401 (missing or invalid key). Check the [Troubleshooting](#troubleshooting) section below.

---

### Step 6: Validate with curl and logs

**API (with key):**

```bash
KEY=$(grep '^OFDD_API_KEY=' /home/ben/open-fdd/stack/.env | cut -d= -f2-)
curl -s -H "Authorization: Bearer $KEY" http://localhost:8000/capabilities
```

You should see JSON with `version` and `features`.

**Logs if something is wrong:**

```bash
docker logs -f homeassistant
docker logs -f openfdd_api
```

Use these to debug 401/auth issues or missing entities.

### How to test after code changes (API or integration)

Do **everything via bootstrap** (stack rebuild, HA addon image, integration copy). No manual `docker compose build` or copy steps.

**One command (full stack + addon image + integration copy + optional addon folder copy):**

```bash
cd /home/ben/open-fdd
./scripts/bootstrap.sh --with-ha /home/ben/homeassistant/config
```

(Use your real HA config path. Or set `export OFDD_HA_CONFIG=/path/to/ha/config` and run `./scripts/bootstrap.sh --with-ha`.)

This will:

1. Build and start the **full stack** (API, DB, Grafana, BACnet, etc.) — so the new `GET /timeseries/latest` and any API changes are live.
2. Build the **HA addon image** `openfdd-addon:local`.
3. **Copy** `stack/ha_integration/custom_components/openfdd` into `config/custom_components/openfdd` and **restart** the HA container (`OFDD_HA_CONTAINER`, default `homeassistant`).
4. If **`OFDD_HA_ADDONS`** is set to your HA addons directory, copy `stack/ha_addon` there so the addon appears in Supervisor.

**Test the new API** (optional):

```bash
KEY=$(grep '^OFDD_API_KEY=' stack/.env | cut -d= -f2-)
curl -s -H "Authorization: Bearer $KEY" "http://localhost:8000/timeseries/latest"
```

You should get a JSON array of `{ "point_id", "external_id", "equipment_id", "value", "ts" }` (empty `[]` if no points or no scraped data yet).

**In HA:** Open **Settings → Devices & services → Open-FDD**. You should see one sensor per point under each equipment device (e.g. AHU-1, VAV-1). Add them to the Overview to see values and use `is_stale` for conditional styling.

**Single-purpose options** (if you only want one of the steps):

- Integration copy only: `./scripts/bootstrap.sh --ha-install-integration /path/to/ha/config`
- Addon image + integration: `./scripts/bootstrap.sh --ha-addon --ha-install-integration /path`

---

### Troubleshooting

| Problem | Cause | What to do |
|--------|--------|------------|
| **`-v: command not found`** | Docker args pasted as separate commands | Paste the full `docker run -d \` block as one command (all lines together). |
| **Permission denied** in `config/custom_components` | `config` owned by root after Docker created it | Run `sudo mkdir -p ...`, `sudo cp -r ...`, then `sudo chown -R $(whoami):$(whoami) .../custom_components`. |
| **HA integration: “Failed to set up”** | API returns 401 (missing or wrong API key) | Ensure **URL** is `http://localhost:8000` and **API key** matches the value in `/home/ben/open-fdd/stack/.env` (`OFDD_API_KEY=...`). Test with `curl -H "Authorization: Bearer KEY" http://localhost:8000/capabilities`. |
| **No entities or devices** | API has no sites/equipment/points yet | Add a site and equipment via the API or Swagger (http://localhost:8000/docs). The integration creates one HA area per site, one HA device per equipment, and one sensor per point (value from GET /timeseries/latest). Ensure the BACnet scraper has written data so /timeseries/latest returns readings. |
| **Swagger /docs "Try it out" returns 401** | API has auth enabled; requests from Swagger do not include the key by default | Open **http://&lt;host&gt;:8000/docs**, click **Authorize**, paste the value of `OFDD_API_KEY` from `stack/.env`, then close. All "Try it out" requests will send `Authorization: Bearer &lt;key&gt;`. For curl: `curl -H "Authorization: Bearer $KEY" http://&lt;host&gt;:8000/equipment`. |
| **Integration logo/icon not showing** | `brand/` layout or **HA version** | Put `icon.png`, `icon@2x.png`, `logo.png`, `logo@2x.png` in **`custom_components/openfdd/brand/`**. The backend only serves them from that path in **Home Assistant 2026.3.0 or newer**. If `curl .../api/brands/integration/openfdd/icon.png` returns **404**, check your HA version (Settings → System → Updates): on **2025.x or older**, the icon will not load from local `brand/`; upgrade to **2026.3+** for it to work. Re-copy the integration, restart HA, then hard-refresh the browser. For the **addon**: put `icon.png` and `logo.png` in `stack/ha_addon/openfdd/`; the addon uses `panel_icon: mdi:air-filter` for the sidebar. |

**Where to check logs:**

- Home Assistant: `docker logs -f homeassistant`
- Open-FDD API: `docker logs -f openfdd_api`

---

### What you should see in Home Assistant

- **Settings → Devices & services:** An **Open-FDD** integration entry and its **logo** (from `brand/icon.png`; hard-refresh if it doesn’t appear).
- **One “Open-FDD” device** (gateway). For each **site** from GET /sites you get one **HA Area** (e.g. TestBenchSite). For each **equipment** from GET /equipment you get one **HA Device** (e.g. AHU-1, VAV-1) in that area.
- **Point telemetry:** For each **point** from GET /points the integration creates one **sensor** under the matching equipment device (or the Open-FDD device if the point has no equipment). The sensor state is the **latest value** from the database (same data the BACnet scraper writes). Attributes include `data_age_seconds` and `is_stale` (true when age &gt; 5 minutes) so you can style cards by color on the overview (BAS-style).
- To verify: call GET /sites, GET /equipment, GET /points, and GET /timeseries/latest (e.g. via Swagger); you should see the same areas, devices, and point sensors in HA.

### How the area page gets its data

When you open an area (e.g. **Dashboard → Areas → TestBenchSite** or `/home/areas-testbenchsite`), HA shows devices and entities assigned to that area. The data flow is:

1. **Coordinator** (every 30 s) calls the Open-FDD API: **GET /sites**, **GET /equipment**, **GET /points**, **GET /timeseries/latest**. Results are stored in the coordinator.
2. **Area/device sync** (on each coordinator update): Each **site** from the API becomes an **HA Area** (by site name, e.g. TestBenchSite). Each **equipment** becomes an **HA Device** with that area set (e.g. AHU-1, VAV-1 in TestBenchSite).
3. **Sensors**: The integration creates **one sensor per point**; each sensor is attached to the equipment device (or the main Open-FDD device if the point has no equipment). The sensor **state** is the latest value from **GET /timeseries/latest** (same data the BACnet scraper writes to the DB). Attributes include **data_age_seconds** and **is_stale** (true when the reading is older than 5 minutes).
4. **Area page**: HA aggregates by area, so the TestBenchSite area shows the Open-FDD devices (AHU-1, VAV-1, …) and all their point sensors. The values and "last updated" you see come from these sensors.

So the area page does **not** call the API directly; it displays entities created from the coordinator data. To see new or changed data, wait for the next coordinator refresh (30 s) or reload the integration.

### Point telemetry and “stale” indicator (BAS-style)

Telemetry comes from **GET /timeseries/latest**: the most recent reading per point from `timeseries_readings` (written by the BACnet scraper and weather scrapers). HA does **not** read BACnet directly; it uses this API so data is consistent with what Open-FDD has already stored.

- **Adding point sensors to the overview:** Go to **Overview**, edit the dashboard, add a card (e.g. **Entities** or **Glance**), then add the Open-FDD point sensors (e.g. **SA-T**, **DAP-P**) for the equipment you care about.
- **Stale data color:** Each point sensor exposes `is_stale` (true when the last reading is older than 5 minutes) and `data_age_seconds`. In a card or conditional card you can change color or icon when `is_stale` is true (e.g. red when stale, green when fresh), similar to a BAS front-end.
- **Threshold:** The 5‑minute cutoff is defined in the integration as `STALE_DATA_SECONDS` (300). To change it, edit `custom_components/openfdd/const.py` and re-copy the integration.
- **Full history and dashboards:** For time-series charts and long-term analysis, use **Grafana** with the Open-FDD TimescaleDB (see [Grafana dashboards](howto/grafana_dashboards.md) and [Grafana cookbook](howto/grafana_cookbook.md)). HA point sensors are for live overview and control; Grafana is for historical dashboards.

---

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

## Device-per-equipment model (Niagara/JACE-like)

The integration maps Open-FDD to Home Assistant in a supervisory-style layout:

- **Site → Area** — Each Open-FDD site (from GET /sites) gets an HA **Area** (by name). Devices are assigned to the area of their site.
- **Equipment → Device** — Each Open-FDD equipment (GET /equipment) becomes one HA **Device** (device registry entry), with `suggested_area` set to the site’s area. The main **Open-FDD** device is the gateway; equipment devices are linked to it.
- **Faults → binary_sensors** — Faults appear as **binary_sensor** entities under the **equipment** device (not the site). One entity per (equipment, fault_id) from fault definitions; state = active when the fault is in GET /faults/active. Cleared faults keep the entity but turn off.
- **Per-equipment sensors** — Each equipment device gets: **Active fault count**, **Last fault change** (timestamp), plus optional Brick-driven placeholders (see below).
- **Per-equipment buttons** — On each equipment device: **Run FDD**, **BACnet discover** (device_instance from options or inferred from points), **Export TTL** (site’s data model), **Refresh**.
- **BACnet device mapping** — To run “BACnet discover” per equipment, the integration needs a BACnet device instance. It is **inferred** from the first point on that equipment that has `bacnet_device_id`. You can override via **Integration options**: configure a JSON map `equipment_id (UUID) → BACnet device_instance (number)` (Settings → Devices & services → Open-FDD → Configure).
- **Brick “supervisory” entities** — GET /entities/suggested returns Brick-tagged points (e.g. occupancy, OA temp). The integration creates **sensor** / **binary_sensor** entities under the right equipment device as **placeholders** (unavailable until a timeseries read API exists). Use them for UI layout and future automations.

Config flow validates with GET /capabilities (optional API key; retry with Bearer on 401/403). Data is refreshed by a single coordinator (sites, equipment, points_by_equipment, faults_active, fault_definitions, run_fdd_status, capabilities, entities_suggested) every 30s. Optional WebSocket subscription to `/ws/events` refreshes the coordinator on `fault.*` and `fdd.run.*` when capabilities report `websocket: true`.

## Graph-driven integration

Open-FDD is a **graph-based RDF platform**: config, sites, equipment, and points live in the knowledge graph and are serialized to `config/data_model.ttl`. There are no constant files or JSON device configs—everything comes from the graph and the API.

The Home Assistant integration uses the API (which is backed by the graph):

- **Sites and equipment** — Fetched via GET /sites and GET /equipment; Sites become Areas, Equipment become Devices.
- **Fault state** — GET /faults/active, GET /faults/definitions; fault binary sensors and summary sensors use this data.
- **Services** — The integration exposes `openfdd.run_sparql` and the full CRUD/BACnet/data-model services so you can run SPARQL and other API calls from HA; results are published as events.

## Custom integration vs official / where data comes from

This is a **custom integration** (not an official Home Assistant Core integration). For a concise **development reference** (manifest, config flow, coordinator, devices/entities, and links to the official HA docs), see [Home Assistant integration development](home_assistant_development.md). Custom integrations live in the user’s `config/custom_components/` or in a separate repo like this one; **you do not fork Home Assistant Core** to develop or ship a custom integration. Core integrations are merged into [home-assistant/core](https://github.com/home-assistant/core); third-party integrations (like Open-FDD) are installed by copying the component or via HACS.

**HA is a reflection of Open-FDD:** Set up sites, equipment, points, and faults in Open-FDD (via the API, Config UI at `/app/`, or scripts like `graph_and_crud_test.py`). The integration’s coordinator fetches that data from the API every 30s; everything you see in HA (devices, areas, entities) comes from the Open-FDD API. No separate device list or config in HA—discovery and data model live in Open-FDD.

**Developing the integration?** You do **not** need to fork Home Assistant Core or run `script/setup` / `script.scaffold integration`. Open-FDD is a custom integration developed in this repo; see [HA integration development](home_assistant_development.md#open-fdd-what-we-do-and-what-we-dont) for what to do (and optional separate-repo layout for HACS).

## Home Assistant Add-on and Integration

Dockerfile-related and HA packaging live under **stack/** with the rest of the stack:

- **Add-on:** `stack/ha_addon/openfdd/` — packages the Open-FDD API so it runs inside Home Assistant. Configure `api_key` and optional `bacnet_server_url` in add-on options. Build with `./scripts/bootstrap.sh --ha-addon` or use HA Supervisor addon build.
- **Integration:** `stack/ha_integration/custom_components/openfdd/` — config flow (URL + API key), coordinator (sites, equipment, faults, definitions, suggested entities), **device-per-equipment** (Site→Area, Equipment→Device, fault binary_sensors, per-equipment buttons/sensors), and **full API as services**. You can do everything from HA that `scripts/graph_and_crud_test.py` tests: `openfdd.get_health`, `openfdd.get_config` / `openfdd.put_config`, `openfdd.list_sites`, `openfdd.create_site`, `openfdd.get_site`, `openfdd.update_site`, `openfdd.delete_site`, and the same for equipment and points; `openfdd.data_model_serialize`, `openfdd.get_data_model_ttl`, `openfdd.get_data_model_export`, `openfdd.put_data_model_import`, `openfdd.run_sparql`, `openfdd.get_data_model_check`; `openfdd.bacnet_server_hello`, `openfdd.bacnet_whois_range`, `openfdd.bacnet_point_discovery_to_graph`; `openfdd.get_download_csv`, `openfdd.post_download_csv`, `openfdd.get_download_faults`; `openfdd.run_fdd`. Results are fired as events (`openfdd.<service>_result`) so automations can react. If `/capabilities` reports `websocket: true`, the integration can optionally subscribe to `/ws/events` and refresh on `fault.*` and `fdd.run.*` events.

**Version:** Same source as the FastAPI app — **pyproject.toml**. The addon gets it at build time (`./scripts/bootstrap.sh --ha-addon` writes it into config.yaml). The integration gets the Open-FDD version from the API at runtime via GET `/capabilities` (no separate version to sync).

### Integration icon (developers)

Per the [HA integration file structure](https://developers.home-assistant.io/docs/creating_integration_file_structure/#local-brand-images-for-custom-integrations), brand images must live in a **`brand/`** subdirectory so they are served via `/api/brands/integration/{domain}/{image}`. The Open-FDD integration uses this layout:

```
custom_components/openfdd/
├── __init__.py
├── manifest.json
├── ...
└── brand/
    ├── icon.png      (256×256)
    ├── icon@2x.png   (512×512)
    ├── logo.png
    └── logo@2x.png
```

**1. Update icons in the repo:** Resize your source image to 256×256 for `brand/icon.png` and 512×512 for `brand/icon@2x.png`; copy to `brand/logo.png` / `brand/logo@2x.png` if desired.

**2. Deploy to HA:** Re-run the bootstrap so the integration (including `brand/`) is copied and HA is restarted:

```bash
./scripts/bootstrap.sh --ha-install-integration /home/ben/homeassistant/config
```

(Or set `OFDD_HA_CONFIG` and run without the path.)

**3. Test:** Open **Settings → Devices & services** — the Open-FDD card and **Add integration** should show the icon. If not, hard-refresh the browser (Ctrl+Shift+R).

**4. Verify the brand URL is served:** The frontend loads the icon from `/api/brands/integration/openfdd/icon.png`. You can confirm HA is serving it:

- **In the browser (while logged in to HA):** Open a new tab and go to `http://<your-ha-host>:8123/api/brands/integration/openfdd/icon.png`. If you see the image, the backend is serving it (the UI may still be caching an old response).
- **With curl (using a long-lived token):** In HA go to **Profile** → **Long-Lived Access Tokens** → **Create token**. Then run:
  ```bash
  curl -H "Authorization: Bearer YOUR_TOKEN" "http://localhost:8123/api/brands/integration/openfdd/icon.png" -o /tmp/openfdd-icon.png && file /tmp/openfdd-icon.png
  ```
  You should get a PNG file. **If you get 404:** the backend does not serve local `brand/` on your HA version. Local brand images are only supported in **Home Assistant 2026.3.0 or newer**. On 2025.x or older, the brands API only serves from the central CDN (where openfdd is not listed). Upgrade to 2026.3+ for the icon to appear.

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

- **Build the addon image** (from the open-fdd repo root). To get the **full stack and the addon** in one go, run:
  ```bash
  ./scripts/bootstrap.sh && ./scripts/bootstrap.sh --ha-addon
  ```
  The first run starts the stack; the second builds the image `openfdd-addon:local` and prints the API key for the addon/integration. If the stack is already running, you can run only `./scripts/bootstrap.sh --ha-addon` to (re)build the addon image.

- **Install in Home Assistant**
  - Copy the addon folder into your HA addons directory: copy **`stack/ha_addon`** (the folder that contains the `openfdd` addon) to wherever your Home Assistant expects addons (e.g. for **Home Assistant Supervised** on Linux: often `~/homeassistant/addons` or a path you configured for local addons).
  - Ensure the addon uses the image **`openfdd-addon:local`**. How you set that depends on your HA setup: with Supervisor, if the addon is loaded from a local path, you may need to set the addon’s image to `openfdd-addon:local` in the addon configuration (or in the addon’s `config.yaml` if your setup supports an `image` key so Supervisor uses the pre-built image instead of building from the Dockerfile).
  - In HA: **Settings → Add-ons → Add-on store** (or **Local add-ons**), add the Open-FDD addon if it isn’t listed, then start it. Set `api_key` and optional `bacnet_server_url` in the addon options.

- **Run Home Assistant on the same Linux Mint machine**
  - **With addons (recommended if you want the addon):** Use **Home Assistant Supervised** on your Linux Mint host. Install Docker and the Supervisor stack; then add the Open-FDD addon as above and use the image `openfdd-addon:local`.
  - **Without addons:** Run **Home Assistant Container** (Docker) and run the full Open-FDD stack separately (e.g. `./scripts/bootstrap.sh` in the open-fdd repo). Point the Open-FDD integration in HA to the Open-FDD API URL (e.g. `http://<host>:8000`). No addon needed; the integration talks to the API over the network.

### Node-RED

The same API works with **Node-RED**: use a config node for base URL and API key, subscribe to `ws://host:8000/ws/events?token=API_KEY` for events (`fault.*`, `crud.point.*`, `fdd.run.*`), and call REST with `Authorization: Bearer <key>` (e.g. run FDD, write point). Planned contrib nodes: **openfdd-server** (config), **openfdd-events** (WebSocket), **openfdd-api** (REST).
