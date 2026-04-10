---
title: Configuration
nav_order: 12
---

# Configuration

---

## Platform config (RDF + CRUD)

Platform config lives in the **same RDF graph** as Brick and BACnet (`config/data_model.ttl`). No YAML file. **Where:** Bootstrap seeds via PUT /config; API GET/PUT /config and POST /data-model/sparql use the graph. The **entire app is bootstrapped from this data model** (sites, equipment, points, and platform config such as `ofdd:rulesDir`, `ofdd:bacnetScrapeIntervalMin`, etc.). **`rules_dir` (ofdd:rulesDir) remains required**: it is the path where FDD rule YAML files are stored; the frontend upload/download UI manages files *in* that path and does not replace the need for the path itself. **Individual rule YAML files are not stored in the data model**—only the single directory path (e.g. `ofdd:rulesDir "stack/rules"`) is; the files themselves live on disk under that path.

- **Bootstrap:** `./scripts/bootstrap.sh` seeds config via PUT /config (defaults or `OFDD_*` from `stack/.env`).
- **API:** GET /config, PUT /config; query via POST /data-model/sparql.
- **Env at seed:** Set `OFDD_*` in `stack/.env` before first bootstrap to customize the seed.
**Docker:** Set env in `stack/docker-compose.yml` or `stack/.env`; bootstrap uses these when calling PUT /config.

**Rename / multiple configs:** Use different env files (e.g. `platform-prod.env`, `platform-building-a.env`) and start with `docker compose --env-file platform-building-a.env up -d`, or set `OFDD_*` in that file. No built-in “config name” selector; use env files or env vars per deployment.

---

## Platform keys (RDF / GET-PUT /config)
{: #platform-keys-config }

Example keys (GET/PUT /config or OFDD_* at bootstrap seed):

| Key | Default | Description |
|-----|---------|-------------|
| `rule_interval_hours` | 3 | FDD loop run interval (when no trigger file: run every N hours) |
| `lookback_days` | 3 | Days of data loaded per run (each run pulls last N days into the rule engine) |
| `fdd_strict_rules` | false | Env: **`OFDD_FDD_STRICT_RULES`**. When true, the FDD loop uses stricter open-fdd **RuleRunner** behavior (fail fast on bad column maps / non-numeric inputs when open-fdd **≥ 2.3**; see [Expression Rule Cookbook](expression_rule_cookbook#signal-scaling-0--1-fraction-vs-0--100-percent)). Intended for dev/CI, not typical production. |
| `rules_dir` | stack/rules | **Single directory for your rules** (hot reload) |
| `brick_ttl_dir` | — | Optional. Directory containing Brick model TTL (e.g. `config/`); platform uses first `.ttl` or brick_ttl path for FDD column mapping. Optional if using points `brick_type`/fdd_input. See [Data modeling](modeling/overview). |
| `bacnet_enabled` | true | Enable BACnet scraper |
| `graph_sync_interval_min` | 5 | Minutes between serializing the **full** in-memory graph to `data_model.ttl` (API background thread). That write runs `sync_brick_from_db` first, so Brick **`ref:`** external references reflect the DB at serialize time. Env: `OFDD_GRAPH_SYNC_INTERVAL_MIN`. Edit in the React app under **OpenFDD Config** (not Overview). For an immediate refresh after discovery or DB edits, use **Data model → Serialize to TTL** or GET `/data-model/ttl` with save. |
| `bacnet_scrape_interval_min` | 5 | Poll interval (minutes) |
| `bacnet_site_id` | default | Site to tag when scraping (use on **remote gateways** so data is attributed to the right building on the central DB) |
| `bacnet_gateways` | — | Optional. **Central aggregator:** JSON array of `{url, site_id}`; scraper polls each remote diy-bacnet-server in turn. Env: `OFDD_BACNET_GATEWAYS`. |
| `open_meteo_enabled` | true | Enable weather; when true, **FDD loop runs a weather fetch at the start of each run** (same cadence as rules, every `rule_interval_hours`). |
| `open_meteo_interval_hours` | 24 | **Standalone weather-scraper only.** Poll interval (hours) when using the optional weather-scraper container. Ignored when weather is run from the FDD loop. |
| `open_meteo_latitude` | 41.88 | Site latitude |
| `open_meteo_longitude` | -87.63 | Site longitude |
| `open_meteo_timezone` | America/Chicago | Timezone |
| `open_meteo_days_back` | 3 | **Standalone weather-scraper only.** Days of archive to fetch per run. When weather runs with FDD, a 1-day lookback is used (no separate config). |
| `open_meteo_site_id` | default | Site ID for weather points |

**Weather fetch:** Weather is normally fetched **with each FDD run** (same interval as fault rules, e.g. every 3 h), using a **1-day lookback** so the API is not over-used. A standalone weather scraper is only for setups that do not run the FDD loop; do not run both to avoid redundant fetches. The standalone scraper reads config from **GET /config** (like the BACnet scraper) when available.

**Where rules live:** Platform config includes **`rules_dir`** (e.g. `stack/rules`). This path is **required**: the FDD loop and the rules API both use it. Rule YAML files are stored there; you can manage them in two ways. (1) **React frontend (Faults page):** upload, download, delete YAML and **Sync definitions** so the fault_definitions table updates without waiting for the next FDD run. (2) **Files on disk:** edit or add files under the configured path (e.g. `stack/rules/`). Both target the same `rules_dir`; the frontend is the preferred path when you have UI access. See [Fault rules overview](rules/overview) and the [Expression Rule Cookbook](expression_rule_cookbook).

**Hot reload (AFDD tuning):** The FDD loop loads rules from `rules_dir` on every run (no cache). Edit YAML on disk or upload via the frontend → trigger a run (or wait for the schedule) or click **Sync definitions** in the UI → results and the definitions table reflect the new rules. The `rules_dir` path is **RDF-driven** (GET/PUT `/config`, same graph as the rest of platform config). Unit tests: `open_fdd/tests/platform/test_rules_loader.py`, `open_fdd/tests/platform_api/test_rules.py`.

**Rolling window (per rule):** Set `params.rolling_window` in each rule YAML; see [Fault rules for HVAC](rules/overview).

---

## Model context endpoint (external agents)

Open‑FDD can serve its own documentation as plain-text model context for external AI agents (for example an OpenAI-compatible tool like Open‑Claw).

The endpoint is `GET /model-context/docs`.

By default it returns a truncated excerpt of `pdf/open-fdd-docs.txt` (or the file pointed to by `OFDD_DOCS_PATH` if set). If you need specific sections, pass `query=...` for keyword retrieval and control output size with `max_chars`.

Open‑FDD does not embed or run an LLM; you supply the LLM provider externally.

Security note: when `OFDD_API_KEY` is enabled, this endpoint requires Bearer auth like other API routes.


---

## Services that read config from the API (BACnet scraper)

Platform config (e.g. **Scrape interval (min)**) is stored in the data model and served by **GET /config**. Some services need to call the API to get that config so changes in the Config UI take effect.

**BACnet scraper** and **weather scraper (standalone):** Both can read config from **GET /config** (with a short cache) so the Config UI and data model control their behaviour. The BACnet scraper uses `bacnet_scrape_interval_min`; the standalone weather scraper uses `open_meteo_enabled`, `open_meteo_interval_hours`, `open_meteo_days_back`, and the geo/site fields. If GET /config fails (e.g. no `OFDD_API_KEY`), they fall back to env vars.

**BACnet scraper:** The scraper runs on a fixed interval (e.g. every 1, 5, or 10 minutes). It can get that interval in two ways:

1. **From the API (dynamic)** — The scraper calls **GET /config** (with a short cache). It then uses `bacnet_scrape_interval_min` from the response, so whatever you set in the Config UI is what the scraper uses. **This only works when the scraper can authenticate:** the API requires Bearer auth when `OFDD_API_KEY` is set, so the scraper must have **`OFDD_API_KEY`** in its environment (same value as in `stack/.env`). The stack’s `docker-compose.yml` passes `OFDD_API_KEY: ${OFDD_API_KEY:-}` to the bacnet-scraper service for this reason.
2. **Fallback (env)** — If GET /config fails (e.g. 401 because no API key, or API unreachable), the scraper falls back to **`OFDD_BACNET_SCRAPE_INTERVAL_MIN`** from its environment (e.g. 5 in compose). **So if you set an interval in the Config UI but the scraper does not have `OFDD_API_KEY`, it will ignore the UI and keep using the env default.** Rebuild/restart the bacnet-scraper after ensuring `OFDD_API_KEY` is in `stack/.env` and in the scraper’s env: `./scripts/bootstrap.sh --build bacnet-scraper`.

**Summary:** For the Config UI (and data model) to control the BACnet scrape interval, the API must have `OFDD_API_KEY` set and the bacnet-scraper container must receive the same key so it can call GET /config successfully.

---

## BACnet: single gateway, remote gateways, central aggregator

- **Single building (or one remote gateway):** Set `OFDD_BACNET_SERVER_URL` and optionally `OFDD_BACNET_SITE_ID` (e.g. `building-a`). The scraper tags all readings with that site. On a **remote** gateway (diy-bacnet-server + scraper on another subnet), point `OFDD_DB_DSN` at the central Open-FDD DB and set `OFDD_BACNET_SITE_ID` to the site name/UUID used on the central API so data is attributed to that building.
- **Central aggregator (multiple remote gateways):** On the central host, do **not** run local bacnet-server/bacnet-scraper; run only DB, API, Grafana, FDD loop, and (optional) weather. Set `OFDD_BACNET_GATEWAYS` to a JSON array, e.g. `[{"url":"http://10.1.1.1:8080","site_id":"building-a"},{"url":"http://10.1.2.1:8080","site_id":"building-b"}]`, and run one scraper container (or cron) that polls each URL and writes to the central DB with the given `site_id`. Alternatively, deploy one scraper per building elsewhere, each with `OFDD_DB_DSN=central` and `OFDD_BACNET_SITE_ID=<that building>`.

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

In the **data model** and **Points** UI these appear under equipment **Open-Meteo** (type **Weather_Service**); the RDF graph marks that equipment with `ofdd:dataSource "open_meteo"`.

---

## Edge / resource limits

For edge deployments with limited disk, set these at bootstrap (or in `stack/.env`). See [Getting Started — Bootstrap options](getting_started#bootstrap-options).

| Setting | Default | Bootstrap arg | Env (stack/.env) |
|---------|---------|---------------|---------------------|
| **Data retention** | 365 days | `--retention-days N` | `OFDD_RETENTION_DAYS` |
| **Docker log size** | 100m per file | `--log-max-size SIZE` | `OFDD_LOG_MAX_SIZE` |
| **Docker log files** | 3 | `--log-max-files N` | `OFDD_LOG_MAX_FILES` |

**Data retention:** TimescaleDB drops chunks older than the configured interval from `timeseries_readings`, `fault_results`, `host_metrics`, `container_metrics`. Set at first run, e.g. `./scripts/bootstrap.sh --retention-days 180`, or set `OFDD_RETENTION_DAYS` in `stack/.env` before running bootstrap.

**Log rotation:** Containers use `json-file` driver; size and file count come from the table above. Restart the stack after changing so new values apply.

**Accessing logs:** `docker logs <container> --tail 50` (e.g. `openfdd_weather_scraper`, `openfdd_bacnet_scraper`).

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
| `OFDD_BACNET_SITE_ID` | Site to tag when scraping (default: default; use on remote gateways) |
| `OFDD_BACNET_GATEWAYS` | JSON array of {url, site_id} for central aggregator |
| `OFDD_RULES_DIR` | Rules directory (default: stack/rules) |

