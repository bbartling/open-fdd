# Open-FDD Monorepo Plan

**Dev notes (high level, for maintainers).** This file is not the user-facing docs — see **docs/** (and [docs index](docs/index.md)) for architecture, getting started, data modeling, and API reference. For AI-assisted data modeling and the LLM tagging prompt, see **AGENTS.md** and [docs/modeling/ai_assisted_tagging.md](docs/modeling/ai_assisted_tagging.md).

Venv: `python3 -m venv .venv && source .venv/bin/activate`. Install: `pip install -e ".[dev]"` (not `.[test]` — dev has full deps). Tests: `pytest open_fdd/tests/ -v` (93 passed). BACnet scrape: see **Run BACnet scrape** and **Confirm BACnet is scraping** below.

---

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
│   │   ├── config.py, database.py, data_model_ttl.py, graph_model.py, site_resolver.py
│   │   ├── loop.py, rules_loader.py
│   │   └── static/        # Config UI (index.html, app.js, styles.css)
│   └── tests/             # analyst/, engine/, platform/, test_schema.py
├── analyst/                # Entry points: sparql, rules, run_all.sh; rules YAML
├── platform/               # docker-compose, Dockerfiles, SQL, grafana, caddy
│   ├── sql/               # 001_init … 011_polling (migrations)
│   ├── grafana/            # provisioning/datasources only; no dashboards (see docs/howto/grafana_cookbook.md)
│   └── caddy/              # Caddyfile (optional reverse proxy)
├── config/                 # brick_model.ttl (Brick + BACnet discovery, one file), BACnet CSV(s) optional
├── scripts/                # bootstrap.sh, discover_bacnet.sh, fake_*_faults.py
├── tools/
│   ├── discover_bacnet.py  # BACnet discovery → CSV (bacpypes3)
│   ├── run_bacnet_scrape.py # Scrape loop/CLI (data-model or CSV, RPC via diy-bacnet-server)
│   ├── run_weather_fetch.py, run_rule_loop.py, run_host_stats.py
│   ├── graph_and_crud_test.py  # CRUD + RDF + SPARQL e2e (point_discovery_to_graph, optional --bacnet-device-instance)
│   ├── trigger_fdd_run.py, test_crud_api.py
│   └── ...
└── examples/               # cloud_export, brick_resolver, run_all_rules_brick, etc.
```

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
| `OFDD_BRICK_TTL_PATH` | config/brick_model.ttl | Unified TTL file. Brick triples synced from DB; BACnet triples from point_discovery (in-memory graph). Written by graph_model sync (interval or on demand). |
| `OFDD_GRAPH_SYNC_INTERVAL_MIN` | 5 | Minutes between serializing the in-memory graph to brick_model.ttl. |
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
| `OFDD_BACNET_SCRAPE_INTERVAL_MIN` | 5 | Scrape interval (minutes). In Docker set in **platform/.env** (e.g. `=1`) then `docker compose up -d`; compose default is 5. |
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

## Grafana (high level)

**Provisioning:** Only the **TimescaleDB datasource** is provisioned (uid: `openfdd_timescale`, database: `openfdd`). No dashboards are shipped; you build your own with SQL. See **[Grafana SQL cookbook](docs/howto/grafana_cookbook.md)** for datasource setup, DB tables (BACnet/data model, faults, host/container metrics, weather), and copy-paste SQL recipes for BACnet timeseries, Fault Results, Fault Analytics, Weather, and System Resources.

**Data source of truth:** Grafana panels query the **same DB** as the API and scrapers (not YAML or TTL). Scraper interval and enable flags are **env vars** (e.g. `OFDD_BACNET_SCRAPE_INTERVAL_MIN=1` in platform/.env; see table above). If panels show "No data", check that the relevant scraper/FDD has run and the dashboard time range includes recent data.


---

## Unit Tests

Tests live under `open_fdd/tests/`. From repo root with venv active: `pip install -e ".[dev]"` then `pytest open_fdd/tests/ -v` (or just `pytest`).

- **analyst/test_brick_model.py** — Build Brick TTL from analyst config.
- **analyst/test_ingest.py** — Parse path, normalize equipment ID, process inner zip (CSV ingest).
- **analyst/test_run_fdd.py** — Filter rules by equipment, empty equipment types; run FDD pipeline (rules + Brick + runner).
- **engine/test_brick_resolver.py** — Resolve column map from TTL, accept str path, equipment types, disambiguation with mapsToRuleInput.
- **engine/test_runner.py** — Expression rule, bounds rule, out-of-range, flatline, from-dir, FC3 expression, bounds metric units, column map override/Brick class, FC4 hunting.
- **engine/test_weather_rules.py** — Load weather rules, RH out of range, gust &lt; wind.
- **platform/test_bacnet_api.py** — parse_bacnet_ttl_to_discovery (devices and point_discoveries from TTL).
- **platform/test_bacnet_brick.py** — object_type_to_brick (analog, binary, with instance, case-insensitive, unknown); object_identifier_to_brick.
- **platform/test_bacnet_driver.py** — get_bacnet_points_from_data_model empty, normalized rows, filter by site_id.
- **platform/test_config.py** — Platform settings defaults.
- **platform/test_crud_api.py** — Sites list/create/get/patch/delete (incl. 404); equipment list/create/get/delete; points list/create/get/patch/delete, create with BACnet fields, list/patch BACnet fields.
- **platform/test_data_model_api.py** — Data model export empty/point refs, TTL from DB, SPARQL bindings (Brick + BACnet), import updates points, deprecated fdd_input; sample object names from point_discovery response; SPARQL bacnet:Device and object-name bindings.
- **platform/test_data_model_ttl.py** — Prefixes, escape, build TTL empty DB, one site one point, site with equipment and points.
- **platform/test_download_api.py** — Download CSV 404 (site not found, no data), 200 wide/long; download faults 404, 200 CSV/JSON.
- **platform/test_graph_model.py** — bacnet_ttl_from_point_discovery (empty objects, device and object names, name fallback, quote escaping).
- **platform/test_rules_loader.py** — Rules dir hash, empty hash, hot reload rules.
- **platform/test_site_resolver.py** — resolve_site_uuid by UUID, by name, not found with other sites, empty table create false/true.
- **test_schema.py** — FDD result/event to row; results from runner output; events from flag series.

---

## Run BACnet scrape

From repo root with venv active and DB + diy-bacnet-server reachable:

- **One shot (data-model path):**  
  `OFDD_BACNET_SERVER_URL=http://localhost:8080 python tools/run_bacnet_scrape.py --data-model`  
  Uses points in the DB that have `bacnet_device_id`, `object_identifier`, and `polling=true`; calls diy-bacnet **client_read_multiple** per device; writes to `timeseries_readings`.

- **Loop (every N min):**  
  `OFDD_BACNET_SERVER_URL=http://localhost:8080 python tools/run_bacnet_scrape.py --data-model --loop`  
  Uses `OFDD_BACNET_SCRAPE_INTERVAL_MIN` (default 5). Set `OFDD_DB_DSN` if DB is not localhost.

- **Site:** Default site for new readings is `OFDD_BACNET_SITE_ID` (default `"default"`). For data-model path, each point already has a site; scraper uses that.

## Confirm BACnet is scraping

1. **Docker logs (when running in stack)** — Only one BACnet scraper runs: `openfdd_bacnet_scraper`. The other containers that use image `openfdd-bacnet-scraper` are **weather-scraper** and **fdd-loop** (different commands). View BACnet scraper logs: `docker logs -f openfdd_bacnet_scraper`.
2. **Log output** — You should see e.g. `BACnet device device,3456789: read_multiple N points (polling=true)` and `BACnet scrape OK (RPC): N readings written, M points, ts=...`.
3. **DB** — New rows in `timeseries_readings` with recent `ts`:
   - Docker: `docker compose exec db psql -U postgres -d openfdd -c "SELECT ts, point_id, value FROM timeseries_readings ORDER BY ts DESC LIMIT 10;"`
   - Local: `psql "$OFDD_DB_DSN" -c "SELECT ts, point_id, value FROM timeseries_readings ORDER BY ts DESC LIMIT 10;"`
4. **Grafana** — Use the provisioned datasource in Explore or build a dashboard from the [Grafana SQL cookbook](docs/howto/grafana_cookbook.md) and confirm recent series.
5. **API** — `GET /download/csv?site_id=<uuid>&start_date=...&end_date=...` (or POST) returns timeseries CSV for a site; if you get data, scrape is writing.

---

## Data model API: export/import for AI-enhanced Brick tagging

**GET /data-model/export** is the **single export route**: one JSON list of **BACnet discovery (graph) + all DB points** (optionally filtered by site). Each row has `point_id` (null if not yet imported), `bacnet_device_id`, `object_identifier`, `object_name`, `site_id`, `external_id`, `brick_type`, `rule_input`, `unit`, and **`polling`** (default **false** for unimported BACnet rows). Use **?bacnet_only=true** to return only rows that have `bacnet_device_id` (discovery rows). Use for LLM Brick tagging; then **PUT /data-model/import**.

**PUT /data-model/import** updates existing points by `point_id`, or **creates** new points when `point_id` is omitted and `site_id`, `external_id`, `bacnet_device_id`, `object_identifier` are provided (e.g. from GET /data-model/export after LLM tagging). Optional **equipment** array updates `feeds_equipment_id` / `fed_by_equipment_id` for Brick relationships. Import never clears BACnet columns; after all updates the backend rebuilds the RDF from the DB and serializes to TTL (in-memory graph + file). **GET /data-model/ttl**, **POST /data-model/sparql**, **GET /data-model/check**, **POST /data-model/reset** as before.

## BACnet discovery → export → LLM → import → scraping (single source of truth)

End-to-end flow so the data model is the single source of truth for BACnet device/point addresses and timeseries references (aligned with proprietary flows like brick_tagger + run_queries + check_integrity):

1. **Discover** — POST /bacnet/whois_range, then POST /bacnet/point_discovery_to_graph per device. Graph and `config/brick_model.ttl` now have BACnet RDF.
2. **Sites/equipment** — Create site(s) and equipment via CRUD (POST /sites, POST /equipment). Note site_id and equipment_id for tagging.
3. **Export for tagging** — GET /data-model/export (unified: BACnet + DB). Returns all discovered BACnet objects and DB points; unimported rows have point_id null and polling false.
4. **Tag** — Edit JSON in a text editor or send to an LLM (see **LLM tagging workflow** below): set `site_id`, `external_id`, `brick_type`, `rule_input` (and optionally `equipment_id`, `unit`, and equipment `feeds_equipment_id`/`fed_by_equipment_id`). For new rows ensure `site_id`, `external_id`, `bacnet_device_id`, `object_identifier` are set.
5. **Import** — PUT /data-model/import with the tagged JSON (body: `points` and optional `equipment`). Creates new points (no point_id), updates existing points (with point_id), and updates equipment feeds/fed_by. Backend rebuilds RDF from DB and serializes TTL.
6. **Scraping** — BACnet scraper (data-model path) loads points where `bacnet_device_id` and `object_identifier` are set, polls diy-bacnet-server, writes to `timeseries_readings`. Grafana (build from cookbook) queries the same DB.
7. **Integrity** — GET /data-model/check for triple/orphan counts; POST /data-model/sparql for ad-hoc checks. FDD rules use Brick types and rule_input from the same points.

Once scraping is running, the data model (sites, equipment, points with BACnet refs and tags) stays the single source of truth; TTL, timeseries, and dashboards stay in sync.

### Why GET /data-model/ttl might still show data after “delete all + reset”

`GET /data-model/ttl` (and `?save=true`) **always** builds from the **current DB**: it syncs Brick triples from the database, then serializes the in-memory graph. So if the DB still has sites/points, the TTL will contain them. After `python tools/delete_all_sites_and_reset.py`, the DB has no sites (cascade removed points and timeseries). So the next `GET /data-model/ttl?save=true` should return only prefixes (empty triples). If you still see BensOffice or weather points: (1) **Same API** — use the same base URL for the script and for curl (e.g. `BASE_URL=http://192.168.204.16:8000` for both). (2) **No re-creation** — ensure no scraper or other process re-created a site/points between delete+reset and your TTL GET. Verify with `GET /sites` after the script; it should return `[]`.

### Testing BACnet discovery → export → import (not yet tested)

End-to-end test flow:

1. **Start stack** — `./scripts/bootstrap.sh` (db, API, bacnet-server, bacnet-scraper). Ensure diy-bacnet-server is reachable from the API container (`OFDD_BACNET_SERVER_URL=http://host.docker.internal:8080`).
2. **Discover devices** — `POST /bacnet/whois_range` with `start_instance` / `end_instance` (e.g. 3456788–3456790). Then for each device: `POST /bacnet/point_discovery_to_graph` with `device_instance` (and optional `device_name`). This fills the in-memory graph with BACnet triples and updates `config/brick_model.ttl`.
3. **Create a site** — `POST /sites` with `name` (e.g. "BensOffice") so you have a `site_id` for tagging.
4. **Export for tagging** — `GET /data-model/export`. Returns unified list (BACnet + DB); unimported rows have `point_id` null and `polling` false.
5. **Tag** — Edit the JSON (or use the LLM prompt in this doc): set `site_id`, `external_id`, `brick_type`, `rule_input` (and optionally `equipment_id`, `unit`). For new rows ensure `site_id`, `external_id`, `bacnet_device_id`, `object_identifier` are set.
6. **Import** — `PUT /data-model/import` with body `{ "points": [ ... ], "equipment": [ ... ] }`. Creates/updates points and equipment; backend rebuilds RDF and serializes TTL.
7. **Scraping** — BACnet scraper (data-model path) will poll points that have `bacnet_device_id` and `object_identifier` and write to `timeseries_readings`. Grafana can show the same data.

If anything in this flow fails, fix the API or drivers first; then re-run from step 2.

**Testing BACnet discover on Open-FDD Swagger:** No rebuild is required. Ensure the full stack is up (`./scripts/bootstrap.sh` or `docker compose -f platform/docker-compose.yml up -d`) so that **db**, **api**, and **bacnet-server** (diy-bacnet-server) are running. The API container uses `OFDD_BACNET_SERVER_URL=http://host.docker.internal:8080` to reach the BACnet server on the host. Open Swagger at `http://<host>:8000/docs`, then try **POST /bacnet/whois_range** (body: `start_instance`, `end_instance`, e.g. 3456788–3456790) and **POST /bacnet/point_discovery_to_graph** (body: `device_instance` from the whois response). Those proxy to diy-bacnet-server; discovery runs and the in-memory graph is updated. No image rebuild unless you changed open-fdd API or bacnet proxy code.

### Future: auto-create site/point when drivers write

In time, the platform could **auto-create** a site and/or point when a driver (BACnet, Open-Meteo, or a custom API scraper) writes the **first** timeseries row for an unknown key (e.g. `site_id` + `external_id` or device/object). That would keep the data model in sync without requiring CRUD first. Today, scrapers expect sites/points to exist (e.g. weather uses a configured site or creates points under an existing site). A later enhancement is: on first write, create the minimal site/point so the reference exists and the user can later refine tags via CRUD or import.

## Data Model Sync Processes

The data model is synced to the single TTL file so the FDD loop and other readers see the latest Brick and BACnet data. The live store is an **in-memory RDF graph** in `platform/graph_model.py`: an rdflib `Graph()` (triple store: subject–predicate–object). Brick triples are refreshed from the DB on sync; BACnet triples are updated from point_discovery JSON. SPARQL and TTL export read from this graph, so we don’t re-read the file on every request. We keep the BACnet section in memory and debounce writes so a burst of CRUDs triggers one write about 250 ms after the last change instead of one write per operation. The file on disk stays correct with fewer reads and batched writes. At API startup the lifespan loads the graph from file, does one initial write, then starts a **background thread** (`graph_model._sync_loop`) that serializes the graph to `config/brick_model.ttl` every **OFDD_GRAPH_SYNC_INTERVAL_MIN** (default 5) minutes; **POST /data-model/serialize** does the same on demand.

## Bootstrap and client updates (data safety)

**Safe for clients with existing data:** `./scripts/bootstrap.sh --update --maintenance --verify` (and plain `--update`) are designed so **TimescaleDB and application data are not wiped** when you run updates on a client that already has data.

- **Git pull** — Only updates repo files; does not touch the database or volumes.
- **Maintenance (--maintenance)** — Runs `docker container prune`, `docker image prune`, `docker builder prune`. It does **not** run `docker volume prune`. DB and Grafana data live in Docker volumes, so they are preserved.
- **Rebuild / up** — Rebuilds images and runs `docker compose up -d`. Existing named volumes (e.g. TimescaleDB data, Grafana data) are reused; containers are recreated but attach to the same volumes.
- **Migrations** — Scripts in `platform/sql/` are **idempotent** (e.g. `ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`). They add new tables/columns when you pull code that adds a new migration; they do not drop tables or delete data. When no new commits were pulled, the script skips the migration step entirely.

**When could data be lost or corrupted?**

- **Bootstrap never prunes volumes.** So the only ways DB or Grafana data get wiped are:
  - **Manual volume prune** — e.g. `docker volume prune` or `docker system prune -a --volumes`. Don’t use `--volumes` on a host that has client data you care about.
  - **--reset-grafana** — Wipes the Grafana volume only (dashboards/settings). TimescaleDB is untouched.
  - **Bad migration** — A future migration that used `DROP TABLE`, `TRUNCATE`, or `DELETE` without care could remove data. Current migrations are additive only; review any new migration before deploying.
  - **Recreating the DB container with a new volume** — e.g. removing the TimescaleDB volume and starting fresh. Bootstrap does not do that.

**Recommendation:** For client sites, run `./scripts/bootstrap.sh --update --maintenance --verify` to pull latest code, prune build/container cruft, restart services, and confirm BACnet + API respond. Back up the DB (e.g. `pg_dump` or volume backup) before major upgrades if the client requires a recovery guarantee.

### Troubleshooting: 500 on GET /sites, GET /data-model/ttl, POST /data-model/reset

**Symptom:** `GET /sites`, `GET /data-model/ttl?save=true`, or `POST /data-model/reset` return **500** and API logs show:

```text
psycopg2.OperationalError: could not translate host name "db" to address: Temporary failure in name resolution
```

**Cause:** The API container connects to the database using hostname **`db`** (the Docker Compose service name). That name only resolves when the **TimescaleDB** container (`openfdd_timescale`) is running and on the same Docker network as the API. If the DB container is not running, the API gets this error on any endpoint that uses the DB (sites, data-model, etc.).

**Fix:** Bring up the **full** stack so the `db` service is running:

```bash
cd open-fdd
./scripts/bootstrap.sh
# or
docker compose -f platform/docker-compose.yml up -d
```

Then confirm the DB container is up:

```bash
docker ps | grep openfdd_timescale
```

You should see `openfdd_timescale` (or the container that runs the `db` service). If it is missing, run `docker compose -f platform/docker-compose.yml up -d` from the repo root and wait for the db healthcheck to pass; then the API will resolve `db` and DB-dependent routes will work. The config-driven TTL path (`OFDD_BRICK_TTL_PATH` → `config/brick_model.ttl`) and volume mount (`../config:/app/config`) are already set so the data model is written **outside** the container (host `config/brick_model.ttl`); once the DB is reachable, GET /data-model/ttl and reset will work.

## Database design & troubleshooting

**Grafana:** Only the **datasource** is provisioned (`platform/grafana/provisioning/datasources/datasource.yml` → TimescaleDB, uid: openfdd_timescale). No dashboards; build your own with SQL from the [Grafana SQL cookbook](docs/howto/grafana_cookbook.md). Default login: **admin / admin**. To re-apply provisioning: `./scripts/bootstrap.sh --reset-grafana` (wipes Grafana volume; DB unchanged). Verify: `docker exec openfdd_grafana ls -la /etc/grafana/provisioning/datasources/`.

### Database schema (TimescaleDB)

**Stack:** TimescaleDB (PostgreSQL + time-series hypertables). Schema in `platform/sql/` (001_init.sql through 010_equipment_feeds.sql; see docs/howto/operations.md for applying new migrations).

**Cascade deletes:** Foreign keys use `ON DELETE CASCADE`. Deleting a **site** removes its equipment, points, and **all their timeseries_readings** from the DB. Deleting **equipment** removes its points and their timeseries; deleting a **point** removes its timeseries. So when a data model reference is removed via CRUD, the corresponding timeseries data is physically deleted—no manual SQL or container access needed. See [Danger zone](docs/howto/danger_zone.md).

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
| feeds_equipment_id | uuid (FK→equipment) | Optional; Brick: this equipment feeds that one |
| fed_by_equipment_id | uuid (FK→equipment) | Optional; Brick: this equipment is fed by that one |
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
| polling | boolean | Default true; if false, BACnet scraper skips this point |
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

## LLM tagging workflow (export → LLM → import)

1. **Export** — GET `/data-model/export` (e.g. `http://<backend>:8000/data-model/export`). Returns unified JSON (BACnet discovery + DB points); unimported rows have `point_id` null and `polling` false.
2. **Clean** — Remove or omit points not needed for HVAC BACnet polling (e.g. non-HVAC objects, duplicates, or devices not used on this job). Keep only the points that should be tagged and later polled.
3. **Tag with LLM** — Send the cleaned JSON to an external LLM using the prompt below. The mechanical engineer provides feeds/fed-by relationships and iterates with the LLM until satisfied.
4. **Import** — Mechanical engineer copies the completed JSON into the open-fdd backend via **PUT /data-model/import**. The backend updates the data model (points and optional equipment relationships), rebuilds the RDF from the DB, and serializes to TTL. Set **`polling`** to `false` on points that should not be polled by the BACnet scraper; the scraper only polls points where `polling` is true (default).

### Prompt to the LLM

Use this (or adapt it) when sending the export JSON (GET /data-model/export) to an external LLM for Brick tagging:

- **Task:** You are helping tag BACnet discovery data for the Open-FDD building analytics platform. The input is a JSON array of BACnet objects (device instance, object identifier, object name, and optionally existing point_id/site_id/equipment_id).
- **Brick tagging:** For each object, set or suggest: `site_id` (UUID from the building/site), `external_id` (time-series key, e.g. from object name), `brick_type` (BRICK class, e.g. Supply_Air_Temperature_Sensor, Zone_Air_Temperature_Sensor), `rule_input` (name FDD rules use), and optionally `equipment_id`, `unit`.
- **Feeds relationships:** A mechanical engineer will provide which equipment feeds or is fed by which other equipment (Brick `feeds` / `isFedBy`). You will incorporate their `feeds_equipment_id` and `fed_by_equipment_id` (equipment UUIDs) into the JSON where appropriate.
- **Iteration:** Work with the mechanical engineer until they are satisfied with the tagging and relationships.
- **Output:** Return the completed JSON array. The mechanical engineer will copy it into the open-fdd backend (PUT /data-model/import) for use on the job. The backend will create or update points and equipment relationships, then refresh the in-memory data model and TTL for BACnet scraping and FDD.