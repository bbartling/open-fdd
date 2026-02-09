# Open-FDD Monorepo Plan

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

## Grafana: prebuilt dashboards

Pre-provisioned in `platform/grafana/`:

| Dashboard | Purpose |
|-----------|---------|
| **BACnet Timeseries** | `timeseries_readings` joined with `points` — all point values over time. Variable: `$point` to filter by point name. |
| **Fault Results** | `fault_results` — fault flags over time. Variable: `$equipment` to filter by equipment. |

**Provisioning:** Datasource `TimescaleDB` (openfdd) and dashboards load automatically when Grafana starts. No manual setup.

**Add custom panels:** Grafana → Dashboards → Open-FDD → Edit. Variables use `SELECT DISTINCT ...` queries; edit SQL in panel settings.
