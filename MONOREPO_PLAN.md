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

**Stack:** TimescaleDB, Grafana, diy-bacnet-server, bacnet-scraper (loop), CRUD API.  
**Prerequisite:** diy-bacnet-server as sibling of open-fdd.  
**Minimal:** `./scripts/bootstrap.sh --minimal` (DB + Grafana only).

### Bootstrap script (`scripts/bootstrap.sh`)

One script to bring up the platform. Run from repo root (e.g. `./scripts/bootstrap.sh`).

| Invocation | What it does |
|------------|--------------|
| `./scripts/bootstrap.sh` | Full stack: builds and starts DB, Grafana, diy-bacnet-server, bacnet-scraper, API. Waits for Postgres ready (~15s), then prints URLs. |
| `./scripts/bootstrap.sh --verify` | Only checks: lists containers and tests DB reachability. Does not start anything. |
| `./scripts/bootstrap.sh --minimal` | DB + Grafana only (no BACnet server, scraper, or API). Use on constrained hardware or when scraping externally. |

**Requirements:** `docker` and `docker compose` (or `docker-compose`) in PATH.  
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

### 6. Run scraper (once or loop)

```bash
# One-shot scrape (requires OFDD_BACNET_SERVER_URL)
OFDD_BACNET_SERVER_URL=http://localhost:8080 python tools/run_bacnet_scrape.py config/bacnet_discovered.csv

# Loop every N min (OFDD_BACNET_SCRAPE_INTERVAL_MIN, default 5)
OFDD_BACNET_SERVER_URL=http://localhost:8080 python tools/run_bacnet_scrape.py --loop

# Validate CSV only (no scrape)
python tools/run_bacnet_scrape.py --validate-only
```

### 7. BACnet read strategy (RPC-only)

Scraper is **RPC-only** via diy-bacnet-server. Uses `client_read_multiple` (RPM) when a device has 2+ points (one request for all present-values). Falls back to `client_read_property` when:
- client_read_multiple fails (timeout, device error, etc.)
- Device has only 1 point

### 8. Logs (RPC-driven)

Logs show: RPC URL, diy-bacnet-server reachability, devices, points read, rows written, errors.

```
2025-02-01 10:00:00 [INFO] open_fdd.bacnet: BACnet scrape via RPC: http://localhost:8080
2025-02-01 10:00:00 [INFO] open_fdd.bacnet: diy-bacnet-server reachable: http://localhost:8080
2025-02-01 10:00:01 [INFO] open_fdd.bacnet: BACnet device device,3456789: reading 19 points (RPC)
2025-02-01 10:00:02 [INFO] open_fdd.bacnet: BACnet RPC client_read_multiple OK for device,3456789: 18 values
2025-02-01 10:00:03 [INFO] open_fdd.bacnet: BACnet scrape OK (RPC): 25 readings written, 25 points, ts=2025-02-01T10:00:02Z
```

### 9. Rules YAML (host-editable)

Rules live in `open_fdd/rules/`. When using Docker, the API container mounts them read-only. Edit YAML on the host; no rebuild needed. The analyst area (`analyst/rules/`) and `open_fdd/rules/` are both used for FDD tuning.

### 10. Data model (CRUD API)

The API at http://localhost:8000/docs exposes:
- **Sites** — buildings/facilities
- **Points** — timeseries references (external_id, brick_type, fdd_input, equipment_id)
- **Equipment** — devices (AHU, VAV, etc.)

Schema: `platform/sql/` (sites, points, equipment, timeseries_readings, fault_results). Analyst SPARQL validates Brick model in `analyst/sparql/`.

### 11. CSV error handling

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

### Current schema (TimescaleDB)

| Table | Purpose |
|-------|---------|
| `sites` | Buildings/facilities (id, name) |
| `points` | Timeseries references: external_id, site_id, bacnet_device_id, object_identifier, object_name, equipment_id (optional), brick_type, fdd_input |
| `equipment` | Devices (AHU, VAV, etc.); optional hierarchy; currently often empty |
| `timeseries_readings` | Hypertable: ts, site_id, point_id, value |
| `fault_results` | Hypertable: ts, site_id, equipment_id, fault_id, flag_value, evidence |
| `fault_events` | Fault episodes (start_ts, end_ts) |
| `weather_hourly_raw` | Open-Meteo history (when enabled) |
| `weather_fault_daily` | Daily weather fault summaries |

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
