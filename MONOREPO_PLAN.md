# Open-FDD Monorepo Plan


## Directory Structure

```
open-fdd/
├── open_fdd/
│   ├── engine/            # runner, checks, brick_resolver
│   ├── reports/           # fault_viz, docx, fault_report
│   ├── schema/            # FDD result/event (canonical)
│   ├── analyst/           # ingest, to_dataframe, brick_model, run_fdd, run_sparql
│   ├── platform/          # FastAPI, DB, drivers, loop
│   │   ├── api/           # CRUD (sites, points, equipment), bacnet, data_model, download, analytics, run_fdd
│   │   ├── drivers/       # open_meteo, bacnet (RPC + data-model scrape), bacnet_validate
│   │   ├── bacnet_brick.py # BACnet object_type → BRICK class mapping
│   │   ├── config.py, database.py, data_model_ttl.py, site_resolver.py
│   │   ├── loop.py, rules_loader.py
│   │   └── static/        # Config UI (index.html, app.js, styles.css)
│   └── tests/             # analyst/, engine/, platform/, test_schema.py
├── analyst/                # Entry points: sparql, rules, run_all.sh; rules YAML
├── platform/               # docker-compose, Dockerfiles, SQL, grafana, caddy
│   ├── sql/               # 001_init … 009_analytics_motor_runtime (migrations)
│   ├── grafana/            # provisioning/datasources, provisioning/dashboards, dashboards/*.json
│   └── caddy/              # Caddyfile (optional reverse proxy)
├── config/                 # brick_model.ttl (Brick + BACnet discovery, one file), BACnet CSV(s) optional
├── scripts/                # bootstrap.sh, discover_bacnet.sh, fake_*_faults.py
├── tools/
│   ├── discover_bacnet.py  # BACnet discovery → CSV (bacpypes3)
│   ├── run_bacnet_scrape.py # Scrape loop/CLI (data-model or CSV, RPC via diy-bacnet-server)
│   ├── run_weather_fetch.py, run_rule_loop.py, run_host_stats.py
│   ├── trigger_fdd_run.py, test_crud_api.py
│   └── ...
└── examples/               # cloud_export, brick_resolver, run_all_rules_brick, etc.
```



---

## Environmental Variables

All platform settings use the **`OFDD_`** prefix (pydantic-settings; `.env` and env override). **What these do / How the platform runs:** The platform does **not** use OS-level monitoring (no inotify, systemd timers, or cron). Each long-lived process (BACnet scraper, weather scraper, FDD rule loop, host-stats) runs a **polling loop** in Python: do work → `time.sleep(interval)` → repeat. The env vars above set those **intervals** (e.g. BACnet every 5 min, FDD every 3 h, weather every 24 h). So the platform “continuously” runs in the sense that these processes stay up and wake on a schedule; they are not triggered by the OS or by file/DB events. The only extra trigger is the **FDD trigger file** (`OFDD_FDD_TRIGGER_FILE`): when the rule loop is in `--loop` mode it checks for that file every 60 s; if the file exists it runs FDD immediately, deletes the file, and resets the timer (so you can `touch config/.run_fdd_now` or use `tools/trigger_fdd_run.py` to run FDD on demand).

| Variable | Default | Description |
|----------|---------|-------------|
| **Database** | | |
| `OFDD_DB_DSN` | `postgresql://postgres:postgres@localhost:5432/openfdd` | TimescaleDB connection string (used by API, scrapers, FDD loop, host-stats). In Docker, set to `postgresql://postgres:postgres@db:5432/openfdd`. |
| **App** | | |
| `OFDD_APP_TITLE` | Open-FDD API | API title. |
| `OFDD_APP_VERSION` | 0.1.0 | API version (e.g. in `/` and docs). |
| `OFDD_DEBUG` | false | Debug mode. |
| `OFDD_BRICK_TTL_DIR` | data/brick | Unused in current flow. |
| `OFDD_BRICK_TTL_PATH` | config/brick_model.ttl | Unified TTL file (Brick section synced from DB; BACnet discovery section appended by discovery-to-rdf). |
| **FDD loop** | | |
| `OFDD_RULE_INTERVAL_HOURS` | 3 | FDD run interval (hours). |
| `OFDD_LOOKBACK_DAYS` | 3 | Lookback window for timeseries. |
| `OFDD_FDD_TRIGGER_FILE` | config/.run_fdd_now | Touch to trigger run and reset timer. |
| `OFDD_RULES_DIR` | analyst/rules | YAML rules directory (hot reload). |
| **BACnet** | | |
| `OFDD_BACNET_SERVER_URL` | — | diy-bacnet-server base URL (e.g. http://localhost:8080). Required for RPC scrape and API proxy. In Docker API use `http://host.docker.internal:8080`. |
| `OFDD_BACNET_SITE_ID` | default | Site name or UUID to tag when scraping (single gateway). |
| `OFDD_BACNET_GATEWAYS` | — | JSON array of `{url, site_id, config_csv}` for central aggregator. |
| `OFDD_BACNET_SCRAPE_ENABLED` | true | Enable BACnet scraper. |
| `OFDD_BACNET_SCRAPE_INTERVAL_MIN` | 5 | Scrape interval (minutes). |
| `OFDD_BACNET_USE_DATA_MODEL` | true | Prefer data-model scrape over CSV when points have BACnet addressing. |
| **Open-Meteo** | | |
| `OFDD_OPEN_METEO_ENABLED` | true | Enable weather scraper. |
| `OFDD_OPEN_METEO_INTERVAL_HOURS` | 24 | Fetch interval (hours). |
| `OFDD_OPEN_METEO_LATITUDE` | 41.88 | Latitude. |
| `OFDD_OPEN_METEO_LONGITUDE` | -87.63 | Longitude. |
| `OFDD_OPEN_METEO_TIMEZONE` | America/Chicago | Timezone. |
| `OFDD_OPEN_METEO_DAYS_BACK` | 3 | Days of history to fetch. |
| `OFDD_OPEN_METEO_SITE_ID` | default | Site to store weather under. |
| **Host stats** | | |
| `OFDD_HOST_STATS_INTERVAL_SEC` | 60 | host-stats container: interval (seconds) for host/container metrics. |
| **Edge / bootstrap** | | |
| `OFDD_RETENTION_DAYS` | 365 | TimescaleDB retention: drop chunks older than N days (set at bootstrap or in platform/.env). |
| `OFDD_LOG_MAX_SIZE` | 100m | Docker log max size per file. |
| `OFDD_LOG_MAX_FILES` | 3 | Docker log file count per container. |

Optional / legacy: `OFDD_PLATFORM_YAML`, `OFDD_ENV_FILE` (see docs/configuration.md). DB components can be overridden via `OFDD_DB_HOST`, `OFDD_DB_PORT`, `OFDD_DB_NAME`, `OFDD_DB_USER`, `OFDD_DB_PASSWORD` if not using a single DSN.



---

## Unit Tests

Tests live under `open_fdd/tests/`. Run: `pytest` or `pytest open_fdd/tests/ -v` (from repo root, with venv active).

- **analyst/test_brick_model.py** — Build Brick TTL from analyst config.
- **analyst/test_ingest.py** — Parse path, normalize equipment ID, process inner zip (CSV ingest).
- **analyst/test_run_fdd.py** — Filter rules by equipment, empty equipment types; run FDD pipeline (rules + Brick + runner).
- **engine/test_brick_resolver.py** — Resolve column map from TTL, accept str path, equipment types, disambiguation with mapsToRuleInput.
- **engine/test_runner.py** — Expression rule, bounds rule, out-of-range, flatline, from-dir, FC3 expression, bounds metric units, column map override/Brick class, FC4 hunting.
- **engine/test_weather_rules.py** — Load weather rules, RH out of range, gust &lt; wind.
- **platform/test_bacnet_api.py** — Import-discovery 422 when no point_discoveries; import normalized point_discoveries; parse raw point_discovery_result.
- **platform/test_bacnet_brick.py** — object_type_to_brick (analog, binary, with instance, case-insensitive, unknown); object_identifier_to_brick.
- **platform/test_bacnet_driver.py** — get_bacnet_points_from_data_model empty, normalized rows, filter by site_id.
- **platform/test_config.py** — Platform settings defaults.
- **platform/test_crud_api.py** — Sites list/create/get/patch/delete (incl. 404); equipment list/create/get/delete; points list/create/get/patch/delete, create with BACnet fields, list/patch BACnet fields.
- **platform/test_data_model_api.py** — Data model export empty/point refs, TTL from DB, SPARQL bindings, import updates points, deprecated fdd_input.
- **platform/test_data_model_ttl.py** — Prefixes, escape, build TTL empty DB, one site one point, site with equipment and points.
- **platform/test_download_api.py** — Download CSV 404 (site not found, no data), 200 wide/long; download faults 404, 200 CSV/JSON.
- **platform/test_rules_loader.py** — Rules dir hash, empty hash, hot reload rules.
- **platform/test_site_resolver.py** — resolve_site_uuid by UUID, by name, not found with other sites, empty table create false/true.
- **test_schema.py** — FDD result/event to row; results from runner output; events from flag series.

---

## Data Model Sync Processes

The data model is still synced to the single TTL file so the FDD loop and other readers see the latest Brick and BACnet data. We keep the BACnet section in memory so each sync doesn’t have to read the file, and we debounce writes so a burst of CRUDs triggers one write about 250 ms after the last change instead of one write per operation. The file on disk stays correct; we just do fewer reads and batch the writes.

## Database design & troubleshooting

**Grafana setup:** Grafana runs as a container (`platform/docker-compose.yml`). Datasource and dashboards are **provisioned** at startup from `platform/grafana/`: `provisioning/datasources/datasource.yml` (TimescaleDB, uid: openfdd_timescale) and `provisioning/dashboards/dashboards.yml` (loads JSON from `dashboards/`). Dashboards include BACnet timeseries, Fault Results, Fault Analytics, Weather, and System Resources. Default login: **admin / admin**. If datasource or dashboards are wrong after an upgrade or volume reuse, run `./scripts/bootstrap.sh --reset-grafana` to wipe the Grafana volume and re-apply provisioning; DB data is unchanged. To verify: `docker exec openfdd_grafana ls -la /etc/grafana/provisioning/datasources/` and `.../dashboards/`.

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

