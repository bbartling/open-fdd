# Open-FDD Monorepo Plan

## What is Open-FDD?

Open-FDD is an open-source edge analytics platform for smart buildings that ingests BACnet and other OT telemetry, stores it in TimescaleDB, and runs rule-based fault detection and diagnostics locally with Grafana dashboards and APIs. As the open alternative to proprietary tools like SkyFoundry's SkySpark, it gives operators full control, lower cost, and cloud-agnostic deployment while already powering real-world HVAC optimization and commissioning workflows.

## Goal
Single monolithic repo: open-fdd (rules engine) + open-fdd-datalake (analyst) + open-fdd-core (IoT/platform) + BACnet/Open-Meteo drivers.

## Canonical FDD Schema (Foundation)

### Real-time FDD result (per sample)
- `ts` — timestamp
- `site_id` — site/building
- `equipment_id` — equipment (e.g. hp_A100_3)
- `fault_id` — rule flag (e.g. hp_discharge_cold_flag)
- `flag_value` — 0 or 1
- `evidence` — optional JSON (sensor values at fault)

### Fault event (episode)
- `site_id`, `equipment_id`, `fault_id`
- `start_ts`, `end_ts`, `duration_seconds`
- `evidence` — optional

## Directory Structure

```
open-fdd/
├── open_fdd/
│   ├── engine/           # runner, checks, brick_resolver
│   ├── reports/          # fault_viz, docx, fault_report
│   ├── rules/            # YAML rules
│   ├── schema/           # FDD result/event (canonical)
│   ├── analyst/          # ingest, to_dataframe, brick_model, run_fdd, run_sparql
│   ├── platform/         # FastAPI, DB, drivers, loop
│   │   ├── api/          # CRUD (sites, points, equipment)
│   │   ├── drivers/      # open_meteo, bacnet (RPC-only)
│   │   ├── config.py, database.py, loop.py
│   │   └── rules_loader.py  # YAML hot-reload
│   └── tests/
├── analyst/               # Entry points: sparql, rules, run_all.sh
├── platform/              # docker-compose, Dockerfiles, SQL, grafana
├── config/                # Platform config; BACnet CSV(s) go here
├── tools/
│   ├── discover_bacnet.py # BACnet discovery → CSV (bacpypes3)
│   └── run_bacnet_scrape.py # Scrape loop/cli (RPC via diy-bacnet-server)
└── examples/
```

## Phases

### Phase 1: Schema + Datalake integration ✅
- [x] Create `open_fdd/schema/fdd_result.py` (canonical)
- [x] Move datalake → `open_fdd/analyst/`
- [x] Analyst run_all.sh, sparql, rules

### Phase 2: Core integration ✅
- [x] Create `open_fdd/platform/` (config, database, loop)
- [x] Canonical fault_results schema (equipment_id)
- [x] Minimal run loop: read timeseries → run FDD → write fault_results

### Phase 3: Drivers ✅
- [x] Open-Meteo driver (from core)
- [x] BACnet driver (RPC-only via diy-bacnet-server; discover_bacnet.py uses bacpypes3)
- [x] tools/discover_bacnet.py

### Phase 4: Config + hot-reload ✅
- [x] Rule interval (N hours), lookback (N days)
- [x] YAML hot-reload (HotReloadRules)
- [x] Scrape intervals (BACnet, Open-Meteo)
- [x] config/platform.example.yaml

### Phase 5: Grafana + polish ✅
- [x] Prebuilt dashboards (BACnet timeseries, fault results)
- [x] Grafana provisioning (datasource, dashboard variables)
- [ ] Unit tests for rules, integration tests

---

## End-to-end: Docker stack (recommended)

| Step | Command |
|------|---------|
| 1. Start full stack | `./scripts/bootstrap.sh` |
| 2. Verify | `./scripts/bootstrap.sh --verify` |
| 3. View logs | `docker compose -f platform/docker-compose.yml logs -f` |
| 4. Grafana | http://localhost:3000 (admin/admin) → Open-FDD folder |
| 5. API (CRUD) | http://localhost:8000/docs |
| 6. BACnet server | http://localhost:8080/docs (diy-bacnet-server Swagger) |

**Stack:** TimescaleDB, Grafana, diy-bacnet-server, bacnet-scraper (loop), weather-scraper (Open-Meteo loop), CRUD API.  
**Prerequisite:** diy-bacnet-server as sibling of open-fdd.  
**Minimal:** `./scripts/bootstrap.sh --minimal` (DB + Grafana only).

### Bootstrap script (`scripts/bootstrap.sh`)

One script to bring up the platform. Run from repo root (e.g. `./scripts/bootstrap.sh`).

| Invocation | What it does |
|------------|--------------|
| `./scripts/bootstrap.sh` | Full stack: builds and starts DB, Grafana, diy-bacnet-server, bacnet-scraper, weather-scraper, API. Waits for Postgres ready (~15s), then prints URLs. |
| `./scripts/bootstrap.sh --verify` | Only checks: lists containers and tests DB reachability. Does not start anything. |
| `./scripts/bootstrap.sh --minimal` | DB + Grafana only (no BACnet server, scraper, or API). Use on constrained hardware or when scraping externally. |

**Requirements:** `docker` and `docker compose` (or `docker-compose`) in PATH.  
**Schema/migrations:** New installs get the full schema from `platform/sql/` (mounted into the DB container as init scripts). After Postgres is up, bootstrap also runs idempotent migrations `004_fdd_input.sql` and `005_bacnet_points.sql` so **existing** DBs get new columns (e.g. `fdd_input`) without manual steps.  
**After adding/editing dashboards or datasource YAML:** Recreate Grafana so it reloads provisioning:  
`docker compose -f platform/docker-compose.yml up -d --force-recreate grafana`

### Service ports

| Service | Port | Purpose |
|---------|------|---------|
| API | 8000 | CRUD API, Swagger docs |
| Grafana | 3000 | Dashboards |
| TimescaleDB | 5432 | PostgreSQL |
| diy-bacnet-server | 8080 | JSON-RPC API (HTTP) |
| diy-bacnet-server | 47808 | BACnet/IP (UDP) |

`bacnet-server` uses `network_mode: host`, so it listens on the host's 8080 and 47808. The others map ports via Docker.

### URLs (from LAN)

Replace `192.168.204.16` with your edge device's IP (`hostname -I`):

| Service | URL |
|---------|-----|
| Grafana | http://192.168.204.16:3000 |
| Open-FDD API | http://192.168.204.16:8000/docs |
| BACnet Swagger | http://192.168.204.16:8080/docs |

### Stop, restart, reboot

```bash
# Stop stack
docker compose -f platform/docker-compose.yml down

# Restart stack
docker compose -f platform/docker-compose.yml up -d

# Reboot: containers stop and do NOT start automatically unless you configure
# Docker or systemd to start them on boot (e.g. restart: unless-stopped + Docker enabled)
```

### Quick health checks

```bash
# Scraper activity
docker logs openfdd_bacnet_scraper --tail 15

# RAM, swap, load, container stats
free -h && uptime && echo "---" && docker stats --no-stream
```

### Ensure data is flowing via the API

Use the CRUD API to confirm scrapers are writing and the app sees sites, points, and (via Grafana) time-series data.

**Copy-paste curl checks:**

```bash
curl -s http://localhost:8000/health && echo ""
curl -s http://localhost:8000/sites | head -c 300
curl -s http://localhost:8000/points | head -c 500
curl -s http://localhost:8000/data-model/export | head -c 600
```

**Commands reference:**

| Goal | Command |
|------|---------|
| Run all tests | `pytest open_fdd/tests/ -v` |
| Run data-model tests | `pytest open_fdd/tests/platform/test_data_model_ttl.py open_fdd/tests/platform/test_data_model_api.py -v` |
| API up | `curl -s http://localhost:8000/health` |
| Sites in DB | `curl -s http://localhost:8000/sites` |
| Points in DB | `curl -s http://localhost:8000/points` |
| Data-model export | `curl -s http://localhost:8000/data-model/export` |
| Time-series data | Grafana → BACnet Timeseries dashboard |
| Scraper activity | `docker logs openfdd_bacnet_scraper --tail 15` and `docker logs openfdd_weather_scraper --tail 15` |

**Expected:** `/health` → `{"status":"ok"}`; `/sites` → JSON array of sites; `/points` → JSON array of points (empty until scrapers run); `/data-model/export` → points as JSON. Time-series: use Grafana.

**If /points returns 500:** Often `column fdd_input does not exist` — the DB was created before migration 004. Run: `docker compose -f platform/docker-compose.yml exec db psql -U postgres -d openfdd -c "ALTER TABLE points ADD COLUMN IF NOT EXISTS fdd_input text;"` (or re-run bootstrap; it now applies 004 and 005 after Postgres is up).

**If /data-model/export returns 404:** Rebuild API image so it includes data-model routes: `docker compose -f platform/docker-compose.yml build api && docker compose -f platform/docker-compose.yml up -d api`.


## Monitoring resources (edge devices)

On constrained hardware, monitor RAM, CPU, and load to avoid seizures:

| Command | Purpose |
|---------|---------|
| `free -h && uptime` | RAM (used/free/available), swap, load average |
| `ps aux --sort=-%mem \| head -10` | Top memory consumers |
| `ps aux --sort=-%cpu \| head -10` | Top CPU consumers |
| `docker stats --no-stream` | Container CPU/memory |
| `docker compose -f platform/docker-compose.yml logs -f bacnet-scraper` | Scrape activity |

**Overload signs:** load average > number of CPUs, swap in use, `docker stats` showing sustained high CPU/memory. Consider `--minimal` (DB + Grafana only) or raising `OFDD_BACNET_SCRAPE_INTERVAL_MIN` if the host is underpowered.

## BACnet scraping (manual / outside Docker)

| Step | Command |
|------|---------|
| 1. Start DB + Grafana | `cd platform && docker compose up -d db grafana` |
| 2. Scrape (once) | `OFDD_BACNET_SERVER_URL=http://localhost:8080 .venv/bin/python3 tools/run_bacnet_scrape.py config/bacnet_discovered.csv` |
| 3. Scrape (loop) | `OFDD_BACNET_SERVER_URL=http://localhost:8080 .venv/bin/python3 tools/run_bacnet_scrape.py --loop` |

---

## Setup: BACnet Discovery & Scrape

### 1. Discover devices → CSV

```bash
pip install bacpypes3 ifaddr
python tools/discover_bacnet.py 1 346000 -o config/bacnet_discovered.csv --warnings
```

For devices in higher instance ranges (e.g. 3456789, 3456790):

```bash
python tools/discover_bacnet.py 1 3456800 -o config/bacnet_discovered.csv --warnings
```

### 2. Trim CSV to points to scrape

**Edit `config/bacnet_discovered.csv`** (or a copy like `config/bacnet_ahu.csv`).

- Delete rows for objects you don’t want to scrape (e.g. `device`, `network-port`, `calendar`, `schedule`).
- Keep rows for analog-input, analog-value, binary-input, etc. that you need for FDD.
- The BACnet driver reads this CSV and fetches `present-value` only for the rows left in the file.

Example: keep only AHU points (SA-T, MA-T, RA-T, DAP, etc.) for one device; keep VAV points (ZoneTemp, VAVFlow, etc.) for another. You can also split into `config/bacnet_ahu.csv`, `config/bacnet_vav.csv` and run scrape per file.

### 3. Start stack (Docker)

**Full stack (recommended):**
```bash
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh
```

**Minimal (DB + Grafana only):**
```bash
./scripts/bootstrap.sh --minimal
```

**Manual:**
```bash
cd platform && docker compose up -d db grafana
```

**First time or after adding Grafana dashboards:** Recreate Grafana to load provisioning:
```bash
cd platform && docker compose up -d --force-recreate grafana
```

Grafana: http://localhost:3000 (admin/admin). DB: localhost:5432/openfdd (postgres/postgres).

### 4. Run BACnet scrape (into TimescaleDB)

**Requires:** diy-bacnet-server running + `OFDD_BACNET_SERVER_URL` + `OFDD_DB_DSN`

```python
from open_fdd.platform.drivers.bacnet import run_bacnet_scrape
from pathlib import Path

run_bacnet_scrape(
    csv_path=Path("config/bacnet_discovered.csv"),
    site_id="default",
    equipment_id="bacnet",
)
```

Or CLI: `OFDD_BACNET_SERVER_URL=http://localhost:8080 python tools/run_bacnet_scrape.py config/bacnet_discovered.csv`  
See `platform/sql/` for schema.

### 5. Enable/disable scraping (like Volttron)

```bash
# Disable BACnet scrape
export OFDD_BACNET_SCRAPE_ENABLED=false

# Enable (default)
export OFDD_BACNET_SCRAPE_ENABLED=true
```

### 6. Open-Meteo weather (optional)

Weather is fetched from the Open-Meteo archive API (hourly temp, RH, dewpoint, wind, gust) and stored in `timeseries_readings` under a site. Used by weather FDD rules (e.g. `weather_rh_out_of_range`, `weather_gust_lt_wind`).

**Config (env or `config/platform.yaml`):**

| Setting | Env var | Default | Description |
|---------|---------|---------|-------------|
| Enable | `OFDD_OPEN_METEO_ENABLED` | true | Set false to disable. |
| Interval | `OFDD_OPEN_METEO_INTERVAL_HOURS` | 24 | How often to fetch (e.g. once per day). |
| Latitude | `OFDD_OPEN_METEO_LATITUDE` | 41.88 | Site latitude. |
| Longitude | `OFDD_OPEN_METEO_LONGITUDE` | -87.63 | Site longitude. |
| Timezone | `OFDD_OPEN_METEO_TIMEZONE` | America/Chicago | For hourly timestamps. |
| Days back | `OFDD_OPEN_METEO_DAYS_BACK` | 3 | Number of days of history per fetch. |
| Site | `OFDD_OPEN_METEO_SITE_ID` | default | Site name or UUID to store weather under (created if missing). |

**Docker:** The `weather-scraper` service runs `tools/run_weather_fetch.py --loop` with the above env vars. Override in `docker-compose.yml` or use a `config/platform.yaml` mount to set your coordinates.

**One-shot or loop (host):**

```bash
# One-shot (uses OFDD_* env vars)
OFDD_OPEN_METEO_LATITUDE=40.71 OFDD_OPEN_METEO_LONGITUDE=-74.01 python tools/run_weather_fetch.py

# Loop every N hours
OFDD_OPEN_METEO_INTERVAL_HOURS=24 python tools/run_weather_fetch.py --loop
```

**Disable in Docker:** Set `OFDD_OPEN_METEO_ENABLED: "false"` for the weather-scraper service, or remove the service from the compose file.

### 7. Run BACnet scraper (once or loop)

```bash
# One-shot scrape (requires OFDD_BACNET_SERVER_URL)
OFDD_BACNET_SERVER_URL=http://localhost:8080 python tools/run_bacnet_scrape.py config/bacnet_discovered.csv

# Loop every N min (OFDD_BACNET_SCRAPE_INTERVAL_MIN, default 5)
OFDD_BACNET_SERVER_URL=http://localhost:8080 python tools/run_bacnet_scrape.py --loop

# Validate CSV only (no scrape)
python tools/run_bacnet_scrape.py --validate-only
```

### 8. BACnet read strategy (RPC-only)

Scraper is **RPC-only** via diy-bacnet-server. Uses `client_read_multiple` (RPM) when a device has 2+ points (one request for all present-values). Falls back to `client_read_property` when:
- client_read_multiple fails (timeout, device error, etc.)
- Device has only 1 point

### 9. Logs (RPC-driven)

Logs show: RPC URL, diy-bacnet-server reachability, devices, points read, rows written, errors.

```
2025-02-01 10:00:00 [INFO] open_fdd.bacnet: BACnet scrape via RPC: http://localhost:8080
2025-02-01 10:00:00 [INFO] open_fdd.bacnet: diy-bacnet-server reachable: http://localhost:8080
2025-02-01 10:00:01 [INFO] open_fdd.bacnet: BACnet device device,3456789: reading 19 points (RPC)
2025-02-01 10:00:02 [INFO] open_fdd.bacnet: BACnet RPC client_read_multiple OK for device,3456789: 18 values
2025-02-01 10:00:03 [INFO] open_fdd.bacnet: BACnet scrape OK (RPC): 25 readings written, 25 points, ts=2025-02-01T10:00:02Z
```

### 10. Rules YAML (host-editable)

Rules live in `open_fdd/rules/`. When using Docker, the API container mounts them read-only. Edit YAML on the host; no rebuild needed. The analyst area (`analyst/rules/`) and `open_fdd/rules/` are both used for FDD tuning.

### 11. Data model (CRUD API)

The API at http://localhost:8000/docs exposes:
- **Sites** — buildings/facilities
- **Points** — timeseries references (external_id, brick_type, fdd_input, equipment_id)
- **Equipment** — devices (AHU, VAV, etc.)
- **Data model** (under `/data-model`): export points as JSON, bulk-import brick_type/fdd_input, generate TTL from DB, run SPARQL against current model.

**Data-model API (CRUD + TTL in sync):** Single source of truth = DB. Unit tests in `open_fdd/tests/platform/test_data_model_ttl.py` and `test_data_model_api.py` validate TTL generation from DB and the export/import/ttl/sparql endpoints (mocked DB). Deleting a site/equipment/point via CRUD updates the DB; GET `/data-model/ttl` always generates TTL from current DB (no separate file drift). Use **GET /data-model/export** to list points (raw names `external_id`, time-series refs `point_id`, `site_id`, optional `brick_type`/`fdd_input`). Send that JSON to an LLM to add best-fit BRICK class per point, then **PUT /data-model/import** with `points: [{ point_id, brick_type?, fdd_input? }]` to update the DB. **GET /data-model/ttl** returns Brick TTL (optionally `?save=true` to write `config/brick_model.ttl`). **POST /data-model/sparql** runs a SPARQL query against that TTL (you can run queries **right in Swagger**: Try it out → edit the example query → Execute); **POST /data-model/sparql/upload** accepts a `.sparql` file. All data-model routes have **Try it out** examples in the API docs. Use SPARQL to validate time-series refs, BRICK mapping, no orphans (e.g. analyst/sparql queries).

Schema: `platform/sql/` (sites, points, equipment, timeseries_readings, fault_results). Analyst SPARQL validates Brick model in `analyst/sparql/`.

### 11a. FDD rule loop (periodic runs with hot-reload)

The **fdd-loop** service runs every N hours (default 3), pulls last N days of data into pandas, loads rules from YAML (every run), runs all rules (sensor + weather), writes `fault_results`. Analyst edits to `analyst/rules/*.yaml` take effect on the next run; no restart.

| Setting | Env var | Default | Description |
|---------|---------|---------|-------------|
| Interval | `OFDD_RULE_INTERVAL_HOURS` | 3 | Hours between runs |
| Lookback | `OFDD_LOOKBACK_DAYS` | 3 | Days of data per run |
| Rules dir | `OFDD_DATALAKE_RULES_DIR` | analyst/rules | YAML rules (checked first) |
| TTL | `OFDD_BRICK_TTL_PATH` | config/brick_model.ttl | Brick model for column_map |

**One-shot:** `python tools/run_rule_loop.py`  
**Loop:** `python tools/run_rule_loop.py --loop`  
**Docker:** `fdd-loop` service in docker-compose. Mount `analyst/rules` and `config` so YAML and TTL are editable on host.

### 11b. Data modeling: Brick TTL and time-series references

**Analyst (standalone CSV) vs platform (DB + Grafana):**

- **Analyst** (`analyst/`, `open_fdd/analyst/`): Standalone CSV pipeline for one-off or offline analysis. Ingest zip-of-CSVs → equipment catalog → `to_dataframe` → heat_pumps.csv. **Brick TTL** is built from an equipment catalog CSV via `open_fdd.analyst.brick_model.build_brick_ttl(catalog_path)`: each row is an equipment/point; TTL emits Brick classes (e.g. Heat_Pump, Supply_Air_Temperature_Sensor), `rdfs:label` = column name in the DataFrame (e.g. "sat", "zt"), and `ofdd:mapsToRuleInput` for rule inputs. Rules then use `column_map` from `resolve_from_ttl(ttl_path)` so Brick class names map to those column names. This path does **not** use the database; it is for CSV-only workflows. See `analyst/README.md`.
- **Platform (DB + Grafana)**: Source of truth is TimescaleDB. Points in `points` have `external_id` (time-series identifier, e.g. BACnet object_name "SA-T", "ZoneTemp"), plus optional `brick_type` (Brick class) and `fdd_input` (rule input name). FDD loop loads timeseries by site/equipment and builds a DataFrame whose columns are `external_id`s; it uses a **Brick TTL** only to get `column_map` (Brick class → label). For TTL to work with DB data, **rdfs:label in TTL must be the point’s external_id** so that the runner can map Brick classes to the actual column names (external_id) in the DataFrame.

**Starting the data modeling process (platform / Grafana-driven):**

1. **Points from BACnet**  
   Scraper writes to `points` with `external_id` = BACnet `object_name` (from `config/bacnet_discovered.csv`). So the CSV’s `object_name` column is the time-series reference (and matches Grafana point dropdowns).

2. **Where the data model can live**  
   - **In the DB**: Set `points.brick_type` (e.g. `Supply_Air_Temperature_Sensor`) and `points.fdd_input` (e.g. `sat`) via the CRUD API (PATCH /points/{id}). Equipment: set `equipment_type` (e.g. AHU, VAV_AHU) for rule filtering. No TTL required if we add a `resolve_from_db()` path that builds `column_map` from these columns (brick_type/fdd_input → external_id).  
   - **In a TTL file**: Put a Brick TTL in config (e.g. `config/brick_model.ttl` or `config/site_default.ttl`). Each point in TTL should have `rdfs:label` = that point’s **external_id** (so column_map becomes Brick class → external_id). TTL can be generated from the DB (export sites/points/equipment → TTL) or from the BACnet CSV (map object_type/object_name to Brick class; label = object_name).

3. **CRUD API and data model**  
   - **List/export time-series references**: Existing GET /points and GET /sites already expose point names (`external_id`) and DB refs (site_id, point id). Optional: add GET /sites/{id}/points/export or GET /data-model that returns a simple list of (site, external_id, point_id, brick_type, fdd_input) for Grafana or scripts.  
   - **Modify data model**: PATCH /points/{id} supports `brick_type`, `fdd_input`, `equipment_id`; PATCH /equipment supports `equipment_type`. So “primitive” data model editing is already: update brick_type and fdd_input on points, equipment_type on equipment.  
   - **TTL in config**: Config can point to a TTL path (e.g. `brick_ttl_dir: "config"` and a file `config/brick_model.ttl`). Optional future: API endpoint to export current DB → TTL and save to config, or to accept TTL upload and backfill points (e.g. set brick_type/fdd_input from TTL).

4. **Suggested flow**  
   - Run BACnet discovery → trim `config/bacnet_discovered.csv`.  
   - Run scraper → points in DB with `external_id` = object_name.  
   - **Option A**: Assign Brick types in DB via API (PATCH point with brick_type, fdd_input); add `resolve_from_db()` in the FDD loop so no TTL is required.  
   - **Option B**: Generate TTL from DB (tool or API “export data model”) or from BACnet CSV (tool: CSV → TTL with rdfs:label = object_name), place in `config/`, set `brick_ttl_dir`/path to that file. FDD loop keeps using `resolve_from_ttl()`.  
   - Grafana: use existing dashboards (site/device/point from DB). Any “data model” UI can sit on top of the same CRUD API (sites, points, equipment).

**Summary:** Analyst = standalone CSV and CSV-built TTL; leave it as-is for offline/one-off analysis. Platform = DB + Grafana; data model = points.brick_type / points.fdd_input (and equipment.equipment_type), optionally mirrored in a TTL under config. CRUD already allows editing the data model via points and equipment; optional additions are export endpoints (points list, DB → TTL) and TTL path in config.

### 12. CSV error handling

If the CSV has fat-finger errors, validation reports line numbers:

```
ERROR line 5: object_identifier must be 'analog-input,1' format, got: 'analog-input' 
ERROR line 12: invalid device_id 'device,xyz': invalid literal for int()
```

Run `--validate-only` before scraping to catch these.

---

## Grafana: datasource and dashboards

### OpenFDD Timescale datasource

The **TimescaleDB** datasource is provisioned from `platform/grafana/provisioning/datasources/datasource.yml`. Grafana loads it on startup. Dashboards expect this datasource **UID: `openfdd_timescale`** (name shown in UI: "TimescaleDB").

**Provisioned settings:**

| Setting | Value | Note |
|---------|--------|------|
| Host | `db:5432` | Use `db` when Grafana runs in Docker (same compose network). For Grafana on host, use `localhost:5432`. |
| Database | `openfdd` | Must be set in `jsonData.database`; "default database" in UI will not apply. |
| User | `postgres` | Or a read-only user (e.g. `grafanareader`) if you create one. |
| Password | (in secureJsonData) | e.g. `postgres` for default install. |
| SSL / TLS | **Disable** | Require SSL causes "SSL is not enabled on the server" against the default DB container. |
| Version | 1600 (PostgreSQL 16) | Optional; `timescaledb: true` for TimescaleDB features. |

**If the datasource shows an error (e.g. after first run or after DB restart):**

1. **Connections → Data sources → Add data source → PostgreSQL.**
2. **Name:** TimescaleDB (or any; UID should be `openfdd_timescale` if you want existing dashboards to work without re-linking).
3. **Host:** `db` (from Docker) or `localhost` if Grafana is on host. **Port:** `5432`.
4. **Database:** `openfdd`.
5. **User / Password:** e.g. `postgres` / `postgres`.
6. **TLS/SSL mode:** **Disable**.
7. **Save & test.**

**Bootstrap note:** `./scripts/bootstrap.sh` starts DB and Grafana and waits for Postgres. If Grafana starts before the DB is ready, the provisioned datasource may fail its first connection; reload the datasource (Save & test) or restart Grafana after DB is up.

### Prebuilt dashboards

Dashboards are **JSON files** in `platform/grafana/dashboards/` (bacnet_timeseries.json, fault_results.json). Grafana loads them via provisioning on startup. Edit the JSON to change panels/variables; edits in the Grafana UI are saved to Grafana's DB, not back to these files.

| Dashboard | Purpose |
|-----------|---------|
| **BACnet Timeseries** | `timeseries_readings` + `points`. Variables: `$site`, `$device` (bacnet_device_id), `$point`. Default time range: last 6h; refresh: 1m. |
| **Fault Results** | `fault_results` over time. Variable: `$equipment`. |

**Add custom panels:** Grafana → Dashboards → Open-FDD → Edit. Variables use `SELECT ...` queries; edit SQL in panel settings.

---

## Database design & troubleshooting

### Database schema (TimescaleDB)

**Stack:** TimescaleDB (PostgreSQL + time-series hypertables). Schema in `platform/sql/` (001_init.sql, 002_crud_schema.sql, 003_equipment.sql, 004_fdd_input.sql, 005_bacnet_points.sql).

#### Core tables

**sites** — Buildings/facilities.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid (PK) | Unique ID |
| name | text | Display name (e.g. "bens_office") |
| description | text | Optional |
| metadata | jsonb | Optional metadata |
| created_at | timestamptz | Creation time |

---

**equipment** — Devices under a site (AHU, VAV, heat pump, etc.).

| Column | Type | Description |
|--------|------|-------------|
| id | uuid (PK) | Unique ID |
| site_id | uuid (FK→sites) | Parent site |
| name | text | Display name |
| description | text | Optional |
| equipment_type | text | Brick-style type (e.g. AHU, VAV) |
| metadata | jsonb | Optional |
| created_at | timestamptz | Creation time |

---

**points** — Sensor/actuator catalog (Brick-style); links to timeseries.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid (PK) | Unique ID |
| site_id | uuid (FK→sites) | Site |
| equipment_id | uuid (FK→equipment) | Optional; device this point belongs to |
| external_id | text | Logical name (e.g. "SA-T", "ZoneTemp"); unique per site |
| brick_type | text | Brick class (e.g. Supply_Air_Temperature_Sensor) |
| fdd_input | text | Rule input name for FDD (e.g. "sat") |
| unit | text | Unit (e.g. degrees-fahrenheit) |
| description | text | Optional |
| bacnet_device_id | text | Optional; BACnet device reference |
| object_identifier | text | Optional; BACnet object ID |
| object_name | text | Optional; BACnet object name |
| created_at | timestamptz | Creation time |

**Unique:** `(site_id, external_id)`

---

**timeseries_readings** (hypertable) — Time-series values for points; partitioned by time.

| Column | Type | Description |
|--------|------|-------------|
| ts | timestamptz | Timestamp |
| site_id | text | Site reference |
| point_id | uuid (FK→points) | Point |
| value | double precision | Measured value |
| job_id | uuid (FK) | Optional; ingest job |

---

**fault_results** (hypertable) — FDD fault flags over time.

| Column | Type | Description |
|--------|------|-------------|
| ts | timestamptz | Timestamp |
| site_id | text | Site |
| equipment_id | text | Equipment identifier |
| fault_id | text | Fault rule ID |
| flag_value | int | 0 or 1 |
| evidence | jsonb | Optional rule evidence |

---

**fault_events** — Fault episodes (start/end) for annotations (e.g. Grafana).

| Column | Type | Description |
|--------|------|-------------|
| id | uuid (PK) | Unique ID |
| site_id | text | Site |
| equipment_id | text | Equipment |
| fault_id | text | Fault rule ID |
| start_ts | timestamptz | Start time |
| end_ts | timestamptz | End time |
| duration_seconds | int | Duration |
| evidence | jsonb | Optional |

---

**ingest_jobs** — Metadata for CSV ingest runs.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid (PK) | Unique ID |
| site_id | uuid (FK→sites) | Site |
| name | text | Job label |
| format | text | "wide" or "long" |
| point_columns | text[] | Point columns |
| row_count | int | Row count |
| created_at | timestamptz | Creation time |

---

**weather_hourly_raw** (hypertable) — Weather time-series.

| Column | Type | Description |
|--------|------|-------------|
| ts | timestamptz | Timestamp |
| site_id | text | Site |
| point_key | text | Weather variable (e.g. temp_f) |
| value | double precision | Value |

---

**weather_fault_daily** / **weather_fault_events** — Weather-related fault aggregates and events.

#### Hierarchy

```
sites
  └── equipment (optional)
        └── points
  └── points (site-level if equipment_id is null)

points → timeseries_readings (one point → many readings)
```

#### Quick reference

| Table | Purpose |
|-------|---------|
| sites | Buildings/facilities |
| equipment | Devices (AHU, VAV, etc.) under a site |
| points | Sensor/actuator catalog with Brick types, rule inputs |
| timeseries_readings | Time-series values for points |
| fault_results | FDD fault flags over time |
| fault_events | Fault episodes (start/end) |
| ingest_jobs | CSV ingest metadata |
| weather_* | Weather data and weather-related faults |

Hypertables use TimescaleDB time partitioning for efficient time-range queries.

**Device vs equipment:** `bacnet_device_id` on points = BACnet device instance (e.g. 3456789). Grafana filters by this. `equipment` = logical system (AHU, VAV) that may map to one or more devices; used by FDD rules and fault_results.

### Inspect database

```bash
cd ~/open-fdd/platform

# List tables
docker compose exec db psql -U postgres -d openfdd -c "\dt"

# Sites
docker compose exec db psql -U postgres -d openfdd -c "SELECT id, name FROM sites ORDER BY name;"

# Equipment (often empty; filled when Brick/equipment hierarchy exists)
docker compose exec db psql -U postgres -d openfdd -c "SELECT id, site_id, name FROM equipment ORDER BY name LIMIT 20;"

# Points (external_id = point name, bacnet_device_id = device instance)
docker compose exec db psql -U postgres -d openfdd -c "SELECT id, site_id, bacnet_device_id, external_id FROM points ORDER BY external_id LIMIT 20;"

# Latest readings
docker compose exec db psql -U postgres -d openfdd -c "SELECT tr.ts, p.external_id, tr.value FROM timeseries_readings tr JOIN points p ON p.id = tr.point_id ORDER BY tr.ts DESC LIMIT 10;"
```

### Troubleshooting database

| Symptom | Cause | Fix |
|---------|-------|-----|
| "could not translate host name 'db'" | DB container down (e.g. after machine seizure) | `docker compose -f platform/docker-compose.yml up -d db grafana` |
| Grafana datasource error | Provisioning failed or DB unreachable | See **Grafana: datasource and dashboards** above. Add manually: Host `db`, Port `5432`, Database `openfdd`, User `postgres`, Password `postgres`, TLS/SSL Disable. |
| Device dropdown empty in Grafana | `points.bacnet_device_id` all NULL | Rebuild scraper and wait for next scrape; scraper now populates bacnet_device_id |
| No timeseries data | Scraper not running or RPC errors | `docker logs openfdd_bacnet_scraper --tail 30`; check OFDD_BACNET_SERVER_URL, diy-bacnet-server running |
| Duplicate key on points | Same (site_id, external_id) from different devices | Current UNIQUE(site_id, external_id) can conflict if two devices have same point name; use bacnet_device_id in external_id or add composite unique |
