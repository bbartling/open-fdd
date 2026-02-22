---
title: Technical reference
parent: Appendix
nav_order: 1
---

# Technical reference

Developer and maintainer reference: directory layout, environment variables, unit tests, BACnet scrape, data model API, bootstrap, database schema, and LLM tagging workflow. For user-facing docs see the [Documentation](..) index.

**Setup:** `python3 -m venv .venv && source .venv/bin/activate`. Install: `pip install -e ".[dev]"`. Tests: `pytest open_fdd/tests/ -v`. BACnet scrape: see **Run BACnet scrape** and **Confirm BACnet is scraping** below.

---

## Directory structure

```
open-fdd/
├── open_fdd/
│   ├── engine/            # runner, checks, brick_resolver
│   ├── reports/           # fault_viz, docx, fault_report
│   ├── schema/            # FDD result/event (canonical)
│   ├── analyst/           # ingest, to_dataframe, brick_model, run_fdd, run_sparql
│   ├── platform/          # FastAPI, DB, drivers, loop
│   │   ├── api/           # CRUD (sites, points, equipment), config, bacnet, data_model, download, analytics, run_fdd
│   │   ├── drivers/       # open_meteo, bacnet (RPC + data-model scrape), bacnet_validate
│   │   ├── bacnet_brick.py # BACnet object_type → BRICK class mapping
│   │   ├── config.py, database.py, data_model_ttl.py, graph_model.py, site_resolver.py
│   │   ├── loop.py, rules_loader.py
│   │   └── static/        # Config UI (index.html, app.js, styles.css)
│   └── tests/             # analyst/, engine/, platform/, test_schema.py
├── analyst/               # Entry points: sparql, rules, run_all.sh; rules YAML; sparql/*.sparql
├── platform/              # docker-compose, Dockerfiles, SQL, grafana, caddy
│   ├── sql/               # 001_init … 011_polling (migrations)
│   ├── grafana/           # provisioning/datasources only (see Grafana SQL cookbook)
│   └── caddy/             # Caddyfile (optional reverse proxy)
├── config/                # data_model.ttl (Brick + BACnet + platform config), BACnet CSV(s) optional
├── scripts/               # bootstrap.sh, discover_bacnet.sh, fake_*_faults.py
├── tools/
│   ├── discover_bacnet.py # BACnet discovery → CSV (bacpypes3)
│   ├── run_bacnet_scrape.py, run_weather_fetch.py, run_rule_loop.py, run_host_stats.py
│   ├── graph_and_crud_test.py # Full CRUD + RDF + SPARQL e2e (see SPARQL cookbook)
│   ├── bacnet_crud_smoke_test.py # Simple BACnet instance range + CRUD smoke test
│   ├── trigger_fdd_run.py
│   └── ...
└── examples/              # cloud_export, brick_resolver, run_all_rules_brick, etc.
```

---

## Environmental variables

All platform settings use the **`OFDD_`** prefix (pydantic-settings; `.env` and env override). Set on the **host** (e.g. `platform/.env` or in `docker-compose.yml`); Docker passes them into each container. Without Docker they are the current shell/process env. The platform uses **polling loops** (no OS cron); the env vars set **intervals** (e.g. BACnet every 5 min, FDD every 3 h). The only extra trigger is **OFDD_FDD_TRIGGER_FILE** (touch to run FDD now). See [Configuration](../configuration) for full table and [SPARQL cookbook](../modeling/sparql_cookbook) for config in RDF.

| Variable | Default | Description |
|----------|---------|-------------|
| **Database** | | |
| `OFDD_DB_DSN` | `postgresql://postgres:postgres@localhost:5432/openfdd` | TimescaleDB connection string. In Docker use `postgresql://postgres:postgres@db:5432/openfdd`. |
| **App** | | |
| `OFDD_APP_TITLE` | Open-FDD API | API title. |
| `OFDD_APP_VERSION` | 2.0.1 | Fallback when package metadata missing. |
| `OFDD_DEBUG` | false | Debug mode. |
| `OFDD_BRICK_TTL_PATH` | config/data_model.ttl | Unified TTL (Brick + BACnet + config). |
| `OFDD_GRAPH_SYNC_INTERVAL_MIN` | 5 | Minutes between graph serialize to TTL. |
| **FDD loop** | | |
| `OFDD_RULE_INTERVAL_HOURS` | 3 | FDD run interval (hours). |
| `OFDD_LOOKBACK_DAYS` | 3 | Lookback window for timeseries. |
| `OFDD_FDD_TRIGGER_FILE` | config/.run_fdd_now | Touch to trigger run and reset timer. |
| `OFDD_RULES_DIR` | analyst/rules | YAML rules directory (hot reload). |
| **BACnet** | | |
| `OFDD_BACNET_SERVER_URL` | — | diy-bacnet-server URL (e.g. http://localhost:8080). |
| `OFDD_BACNET_SITE_ID` | default | Site to tag when scraping. |
| `OFDD_BACNET_GATEWAYS` | — | JSON array for central aggregator. |
| `OFDD_BACNET_SCRAPE_ENABLED` | true | Enable BACnet scraper. |
| `OFDD_BACNET_SCRAPE_INTERVAL_MIN` | 5 | Scrape interval (minutes). |
| `OFDD_BACNET_USE_DATA_MODEL` | true | Prefer data-model scrape over CSV. |
| **Open-Meteo** | | |
| `OFDD_OPEN_METEO_*` | (see Configuration) | Enabled, interval, lat/lon, timezone, days_back, site_id. |
| **Host stats** | | |
| `OFDD_HOST_STATS_INTERVAL_SEC` | 60 | host-stats container interval (seconds). |
| **Edge / bootstrap** | | |
| `OFDD_RETENTION_DAYS` | 365 | TimescaleDB retention (days). |
| `OFDD_LOG_MAX_SIZE` | 100m | Docker log max size per file. |
| `OFDD_LOG_MAX_FILES` | 3 | Docker log file count. |

**Optional:** `OFDD_ENV_FILE` ([Configuration](../configuration)). Platform config is RDF (GET/PUT /config). `OFDD_API_URL` — used by **bootstrap.sh** when API is not at localhost:8000.

---

## Unit tests

Tests live under `open_fdd/tests/`. Run: `pytest open_fdd/tests/ -v`. All use in-process mocks; no shared DB or live API. For end-to-end (real API, optional BACnet): `python tools/graph_and_crud_test.py` (see [SPARQL cookbook](../modeling/sparql_cookbook)).

- **analyst/** — brick_model, ingest, run_fdd
- **engine/** — brick_resolver, runner, weather_rules
- **platform/** — bacnet_api, bacnet_brick, bacnet_driver, config, crud_api, data_model_api, data_model_ttl, download_api, graph_model, rules_loader, site_resolver
- **test_schema.py** — FDD result/event to row

---

## Run BACnet scrape

With DB and diy-bacnet-server reachable:

- **One shot:** `OFDD_BACNET_SERVER_URL=http://localhost:8080 python tools/run_bacnet_scrape.py --data-model`
- **Loop:** same with `--loop` (uses `OFDD_BACNET_SCRAPE_INTERVAL_MIN`).

**Confirm scraping:** Docker logs `openfdd_bacnet_scraper`; DB `timeseries_readings`; [Grafana SQL cookbook](../howto/grafana_cookbook); API `GET /download/csv`.

---

## Data model API and discovery flow

**GET /data-model/export** — BACnet discovery + DB points (optional `?bacnet_only=true`, `?site_id=...`). Use for [AI-assisted tagging](../modeling/ai_assisted_tagging); then **PUT /data-model/import**.

**PUT /data-model/import** — Points (required) and optional equipment (feeds/fed_by). Creates/updates points; backend rebuilds RDF and serializes TTL.

**Flow:** Discover (POST /bacnet/whois_range, POST /bacnet/point_discovery_to_graph) → Sites/equipment (CRUD) → GET /data-model/export → Tag (LLM or manual) → PUT /data-model/import → Scraping → GET /data-model/check, POST /data-model/sparql for integrity.

See [Data modeling overview](../modeling/overview) and [SPARQL cookbook](../modeling/sparql_cookbook).

---

## Data model sync

Live store: **in-memory RDF graph** (`platform/graph_model.py`). Brick triples from DB; BACnet from point_discovery. SPARQL and TTL read from this graph. Background thread serializes to `config/data_model.ttl` every **OFDD_GRAPH_SYNC_INTERVAL_MIN**; **POST /data-model/serialize** on demand.

---

## Bootstrap and client updates

**Safe for clients:** `./scripts/bootstrap.sh --update --maintenance --verify` does not wipe TimescaleDB or Grafana data (no volume prune). Migrations in `platform/sql/` are idempotent. See [Getting started](../getting_started).

**Troubleshooting 500 (db host unresolved):** Ensure full stack is up so API can resolve hostname `db`. Run `./scripts/bootstrap.sh` or `docker compose -f platform/docker-compose.yml up -d`.

---

## Database schema (TimescaleDB)

Schema in `platform/sql/`. **Cascade deletes:** Site → equipment, points, timeseries; equipment → points, timeseries; point → timeseries. See [Danger zone](../howto/danger_zone).

| Table | Purpose |
|-------|---------|
| **sites** | id, name, description, metadata, created_at |
| **equipment** | id, site_id, name, equipment_type, feeds_equipment_id, fed_by_equipment_id |
| **points** | id, site_id, equipment_id, external_id, brick_type, fdd_input, bacnet_device_id, object_identifier, object_name, polling |
| **timeseries_readings** | ts, point_id, value (hypertable) |
| **fault_results** | ts, site_id, equipment_id, fault_id, flag_value (hypertable) |
| **fault_events** | start_ts, end_ts, fault_id, equipment_id |
| **weather_hourly_raw** | ts, site_id, point_key, value (hypertable) |

---

## LLM tagging workflow

1. **Export** — GET `/data-model/export`.
2. **Clean** — Keep only points to tag and poll.
3. **Tag with LLM** — Use prompt in [AI-assisted tagging](../modeling/ai_assisted_tagging) (and **AGENTS.md** in repo).
4. **Import** — PUT /data-model/import with `points` and optional `equipment`. Set `polling` false on points that should not be scraped.

Prompt summary: Set `site_id`, `external_id`, `brick_type`, `rule_input`; optionally `equipment_id`, `unit`, and equipment `feeds_equipment_id`/`fed_by_equipment_id`. Output is the completed JSON for PUT /data-model/import.
