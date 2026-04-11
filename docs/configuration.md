---
title: Configuration
nav_order: 12
---

# Configuration

---

## Platform config (RDF + CRUD)

Platform config lives in the **same RDF graph** as Brick (`config/data_model.ttl`). Optional legacy BACnet-related keys may still appear in RDF from older imports; **ingestion** is from **VOLTTRON → SQL**, not from Open-F-DD scrapers. No YAML file. **Where:** Bootstrap seeds via PUT /config; API GET/PUT /config and POST /data-model/sparql use the graph. The **entire app is bootstrapped from this data model** (sites, equipment, points, and platform config such as `ofdd:rulesDir`, `ofdd:bacnetScrapeIntervalMin`, etc.). **`rules_dir` (ofdd:rulesDir) remains required**: it is the path where FDD rule YAML files are stored; the frontend upload/download UI manages files *in* that path and does not replace the need for the path itself. **Individual rule YAML files are not stored in the data model**—only the single directory path (e.g. `ofdd:rulesDir "stack/rules"`) is; the files themselves live on disk under that path.

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
| `bacnet_enabled` | true | **Legacy:** BACnet scraper toggle (removed from default Compose). Ignored when **only VOLTTRON** writes SQL. |
| `graph_sync_interval_min` | 5 | Minutes between serializing the **full** in-memory graph to `data_model.ttl` (API background thread). That write runs `sync_brick_from_db` first, so Brick **`ref:`** external references reflect the DB at serialize time. Env: `OFDD_GRAPH_SYNC_INTERVAL_MIN`. Edit in the React app under **OpenFDD Config** (not Overview). For an immediate refresh after discovery or DB edits, use **Data model → Serialize to TTL** or GET `/data-model/ttl` with save. |
| `bacnet_scrape_interval_min` | 5 | **Legacy:** scraper poll interval (minutes); not used in VOLTTRON-only ingest. |
| `bacnet_site_id` | default | **Legacy:** site tag for removed scraper / remote-gateway pattern. Prefer **VOLTTRON** historian site keys in SQL. |
| `bacnet_gateways` | — | **Legacy:** central-aggregator JSON for diy-bacnet gateways. **Not** the default architecture. |
| `open_meteo_enabled` | true | Enable weather; when true, **FDD loop runs a weather fetch at the start of each run** (same cadence as rules, every `rule_interval_hours`). |
| `open_meteo_interval_hours` | 24 | **Standalone weather-scraper only.** Poll interval (hours) when using the optional weather-scraper container. Ignored when weather is run from the FDD loop. |
| `open_meteo_latitude` | 41.88 | Site latitude |
| `open_meteo_longitude` | -87.63 | Site longitude |
| `open_meteo_timezone` | America/Chicago | Timezone |
| `open_meteo_days_back` | 3 | **Standalone weather-scraper only.** Days of archive to fetch per run. When weather runs with FDD, a 1-day lookback is used (no separate config). |
| `open_meteo_site_id` | default | Site ID for weather points |

**Weather fetch:** Weather is normally fetched **with each FDD run** (same interval as fault rules, e.g. every 3 h), using a **1-day lookback** so the API is not over-used. A standalone weather scraper is only for setups that do not run the FDD loop; do not run both to avoid redundant fetches. The standalone scraper reads config from **GET /config** when available.

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

## Config consumers (today)

**Default:** **VOLTTRON** historians and agents write **SQL** using deployment-specific config; they do **not** need Open-F-DD’s **GET /config** for BACnet scrape intervals.

**Optional FastAPI process:** When you run the API, **GET /config** still serves platform RDF keys for the React **Config** UI (rules dir, graph sync, Open-Meteo toggles, **legacy** BACnet keys for forks). **Standalone weather scraper** (if you still run one from `legacy`) can read **GET /config** for `open_meteo_*` fields.

**Legacy BACnet scraper / diy-bacnet central aggregator:** Removed from upstream default Compose. If you maintain a **private fork** that restores those services, consult **`afdd_stack/legacy/README.md`** and git history — do **not** use that pattern for new BACnet ingest; use **[Site VOLTTRON and the data plane (ZMQ)](concepts/site_volttron_data_plane)**.

---

## Open-Meteo weather points

These keys still apply when weather is fetched **with the FDD loop** or a standalone scraper. Values are stored in `timeseries_readings` by `external_id`:

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

**Accessing logs:** `docker logs <container> --tail 50` for any **optional** containers you run (e.g. legacy weather scraper names in a fork). Default compose is **db-only** (+ optional Grafana/Mosquitto).

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
| `OFDD_BACNET_SERVER_URL` | **Legacy / lab only:** diy-bacnet-server base URL if you enable FastAPI proxy routes |
| `OFDD_BACNET_SITE_ID` | **Legacy:** site tag for removed scraper patterns |
| `OFDD_BACNET_GATEWAYS` | **Legacy:** JSON array for removed central-aggregator scraper |
| `OFDD_RULES_DIR` | Rules directory (default: stack/rules) |

