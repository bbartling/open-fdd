---
title: Configuration
nav_order: 12
---

# Configuration

---

## Platform config file

**Where:** Copy `config/platform.example.yaml` to your config file. The platform looks for:

- **Environment:** `OFDD_*` vars (e.g. `OFDD_RULE_INTERVAL_HOURS=6`) override any file.
- **File:** By default the app does not read a YAML path from env; pydantic-settings loads from `.env` and env vars. To use a **named file** (e.g. `platform.yaml`, `my_site.yaml`), set `OFDD_ENV_FILE` or place `.env` in the working directory and point it there, or pass env vars when starting containers.

**Docker:** Set env in `platform/docker-compose.yml` under each service’s `environment:` (e.g. `OFDD_RULE_INTERVAL_HOURS: "6"`). To use a custom config file, mount it and set `OFDD_ENV_FILE` to its path, or set individual `OFDD_*` vars.

**Rename / multiple configs:** Use different env files (e.g. `platform-prod.env`, `platform-building-a.env`) and start with `docker compose --env-file platform-building-a.env up -d`, or set `OFDD_*` in that file. No built-in “config name” selector; use env files or env vars per deployment.

---

## Platform (YAML)

Example keys (see `config/platform.example.yaml`). Copy to your file or set via `OFDD_*` env.

| Key | Default | Description |
|-----|---------|-------------|
| `rule_interval_hours` | 3 | FDD loop run interval (when no trigger file: run every N hours) |
| `lookback_days` | 3 | Days of data loaded per run (each run pulls last N days into the rule engine) |
| `rules_dir` | analyst/rules | **Single directory for your rules** (hot reload) |
| `brick_ttl_dir` | — | Optional. Directory containing Brick model TTL (e.g. `config/`); platform uses first `.ttl` or brick_ttl path for FDD column mapping. Optional if using points `brick_type`/fdd_input. See [Data modeling](modeling/overview). |
| `bacnet_enabled` | true | Enable BACnet scraper |
| `graph_sync_interval_min` | 5 | Minutes between serializing the in-memory graph to `brick_model.ttl` (API background thread). Env: `OFDD_GRAPH_SYNC_INTERVAL_MIN`. |
| `bacnet_scrape_interval_min` | 5 | Poll interval (minutes) |
| `bacnet_use_data_model` | true | Prefer scraping points from the data model (points with `bacnet_device_id`/`object_identifier`); fall back to CSV if none. Env: `OFDD_BACNET_USE_DATA_MODEL`. |
| `bacnet_site_id` | default | Site to tag when scraping (use on **remote gateways** so data is attributed to the right building on the central DB) |
| `bacnet_gateways` | — | Optional. **Central aggregator:** JSON array of `{url, site_id, config_csv}`; scraper polls each remote diy-bacnet-server in turn. Env: `OFDD_BACNET_GATEWAYS`. |
| `bacnet_config_csv` | config/bacnet_discovered.csv | CSV path when using CSV path (fallback or `--csv-only`). Single gateway. |
| `open_meteo_enabled` | true | Enable weather scraper |
| `open_meteo_interval_hours` | 24 | Weather poll interval |
| `open_meteo_latitude` | 41.88 | Site latitude |
| `open_meteo_longitude` | -87.63 | Site longitude |
| `open_meteo_timezone` | America/Chicago | Timezone |
| `open_meteo_days_back` | 3 | Days of archive to fetch |
| `open_meteo_site_id` | default | Site ID for weather points |

**Where to place rules:** Put your project rules in **`analyst/rules/`** (one place). Hot reload: edit YAML → trigger FDD run (or wait for schedule) → view in Grafana. See [Fault rules overview](rules/overview) and the [Expression Rule Cookbook](expression_rule_cookbook).

**Rolling window (per rule):** Set `params.rolling_window` in each rule YAML; see [Fault rules for HVAC](rules/overview).

**BACnet: single gateway, remote gateways, central aggregator**

- **Single building (or one remote gateway):** Set `OFDD_BACNET_SERVER_URL` and optionally `OFDD_BACNET_SITE_ID` (e.g. `building-a`). The scraper tags all readings with that site. On a **remote** gateway (diy-bacnet-server + scraper on another subnet), point `OFDD_DB_DSN` at the central Open-FDD DB and set `OFDD_BACNET_SITE_ID` to the site name/UUID used on the central API so data is attributed to that building.
- **Central aggregator (multiple remote gateways):** On the central host, do **not** run local bacnet-server/bacnet-scraper; run only DB, API, Grafana, FDD loop, and (optional) weather. Set `OFDD_BACNET_GATEWAYS` to a JSON array, e.g.  
  `[{"url":"http://10.1.1.1:8080","site_id":"building-a","config_csv":"config/bacnet_a.csv"},{"url":"http://10.1.2.1:8080","site_id":"building-b","config_csv":"config/bacnet_b.csv"}]`  
  and run one scraper container (or cron) that polls each URL and writes to the central DB with the given `site_id`. Alternatively, deploy one scraper per building elsewhere, each with `OFDD_DB_DSN=central` and `OFDD_BACNET_SITE_ID=<that building>`.

**Open-Meteo weather points** (stored in `timeseries_readings`, `external_id`):

| Point | Description |
|-------|-------------|
| `temp_f` | Temperature (°F) |
| `rh_pct` | Relative humidity (%) |
| `dewpoint_f` | Dew point (°F) |
| `wind_mph` | Wind speed (mph) |
| `gust_mph` | Wind gusts (mph) |
| `wind_dir_deg` | Wind direction (degrees) |
| `shortwave_wm2` | Shortwave radiation (W/m²) |
| `direct_wm2` | Direct radiation (W/m²) |
| `diffuse_wm2` | Diffuse radiation (W/m²) |
| `gti_wm2` | Global tilted irradiance (W/m²) |
| `cloud_pct` | Cloud cover (%) |

---

## Edge / resource limits

For edge deployments with limited disk, set these at bootstrap (or in `platform/.env`). See [Getting Started — Bootstrap options](getting_started#bootstrap-options).

| Setting | Default | Bootstrap arg | Env (platform/.env) |
|---------|---------|---------------|---------------------|
| **Data retention** | 365 days | `--retention-days N` | `OFDD_RETENTION_DAYS` |
| **Docker log size** | 100m per file | `--log-max-size SIZE` | `OFDD_LOG_MAX_SIZE` |
| **Docker log files** | 3 | `--log-max-files N` | `OFDD_LOG_MAX_FILES` |

**Data retention:** TimescaleDB drops chunks older than the configured interval from `timeseries_readings`, `fault_results`, `host_metrics`, `container_metrics`. Set at first run, e.g. `./scripts/bootstrap.sh --retention-days 180`, or set `OFDD_RETENTION_DAYS` in `platform/.env` before running bootstrap.

**Log rotation:** Containers use `json-file` driver; size and file count come from the table above. Restart the stack after changing so new values apply.

**Accessing logs:** `docker logs <container> --tail 50` (e.g. `openfdd_weather_scraper`, `openfdd_bacnet_scraper`). See [Verification](howto/verification#logs).

---

## Environment

`OFDD_`-prefixed vars override YAML:

| Variable | Description |
|----------|-------------|
| `OFDD_DB_HOST` | TimescaleDB host |
| `OFDD_DB_PORT` | TimescaleDB port |
| `OFDD_DB_NAME` | Database name |
| `OFDD_DB_USER` | Database user |
| `OFDD_DB_PASSWORD` | Database password |
| `OFDD_BACNET_SERVER_URL` | diy-bacnet-server base URL (e.g. http://localhost:8080) |
| `OFDD_BACNET_USE_DATA_MODEL` | Prefer data-model scrape; fall back to CSV if no BACnet points in DB (default: true) |
| `OFDD_BACNET_SITE_ID` | Site to tag when scraping (default: default; use on remote gateways) |
| `OFDD_BACNET_GATEWAYS` | JSON array of {url, site_id, config_csv} for central aggregator |
| `OFDD_RULES_DIR` | Rules directory (default: analyst/rules) |
| `OFDD_PLATFORM_YAML` | Path to platform.yaml |

