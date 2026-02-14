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
| `bacnet_enabled` | true | Enable BACnet scraper |
| `bacnet_scrape_interval_min` | 5 | Poll interval (minutes) |
| `bacnet_config_csv` | config/bacnet_device.csv | BACnet device config |
| `open_meteo_enabled` | true | Enable weather scraper |
| `open_meteo_interval_hours` | 24 | Weather poll interval |
| `open_meteo_latitude` | 41.88 | Site latitude |
| `open_meteo_longitude` | -87.63 | Site longitude |
| `open_meteo_timezone` | America/Chicago | Timezone |
| `open_meteo_days_back` | 3 | Days of archive to fetch |
| `open_meteo_site_id` | default | Site ID for weather points |

**Where to place rules:** Put your project rules in **`analyst/rules/`** (one place). Hot reload: edit YAML → trigger FDD run (or wait for schedule) → view in Grafana. See [Rules overview](rules/overview) and the [Expression Rule Cookbook](rules/expression_rule_cookbook).

**Rolling window (per rule):** Set `params.rolling_window` in each rule YAML; see [Rules](rules/overview).

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

For edge deployments with limited disk, bootstrap applies:

| Limit | Value | Where |
|-------|-------|-------|
| **Docker logs** | 100 MB × 3 files (~300 MB per container) | `platform/docker-compose.yml` — `x-log-opts` |
| **Data retention** | 1 year (365 days) | `platform/sql/007_retention.sql` — TimescaleDB `add_retention_policy` |

**Log rotation:** Containers use `json-file` driver with `max-size: 100m`, `max-file: 3`. Prevents logs from filling disk.

**Data retention:** Drops chunks older than 1 year from `timeseries_readings`, `fault_results`, `host_metrics`, `container_metrics`. Typical edge (BACnet + weather, ~hourly) stays under ~200 GB. To change: edit `INTERVAL '365 days'` in `007_retention.sql` (e.g. `'180 days'`, `'2 years'`).

**200 GB hard cap:** Not enforced automatically. If you need a strict limit, add cron or systemd to run `SELECT drop_chunks(...)` when disk usage exceeds a threshold, or use LVM/disk quotas at the host.

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
| `OFDD_BACNET_URL` | diy-bacnet-server base URL |
| `OFDD_RULES_DIR` | Rules directory (default: analyst/rules) |
| `OFDD_PLATFORM_YAML` | Path to platform.yaml |

---

## Rule YAML

Each rule file has:

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Rule identifier |
| `type` | Yes | bounds, flatline, expression, hunting, oa_fraction, erv_efficiency |
| `flag` | Yes | Output column suffix (e.g. `bad_sensor`) |
| `inputs` | Yes | List or dict of input refs |
| `params` | No | Type-specific params |
| `expression` | For expression | Pandas expression string |

---

## Bounds rule

```yaml
name: sensor_bounds
type: bounds
flag: bad_sensor
inputs:
  - oat
  - sat
params:
  low: 40
  high: 90
  # or units: metric for °C
```

---

## Flatline rule

```yaml
name: sensor_flatline
type: flatline
flag: flatline_flag
inputs: [oat, sat]
params:
  tolerance: 0.000001
  window: 12
```

---

## Expression rule

Use Brick class names or column refs as input keys. See [Rules Overview](rules/overview) and [Expression Rule Cookbook](expression_rule_cookbook).
