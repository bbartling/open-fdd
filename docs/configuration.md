---
title: Configuration
nav_order: 12
---

# Configuration

---

## Platform (YAML)

Copy `config/platform.example.yaml` to `platform/platform.yaml` (or set via environment).

| Key | Default | Description |
|-----|---------|-------------|
| `rule_interval_hours` | 3 | FDD loop run interval |
| `lookback_days` | 3 | Days of data to load per run |
| `rolling_window` | 6 | Consecutive samples to flag fault |
| `rules_yaml_dir` | open_fdd/rules | Fallback rules directory |
| `datalake_rules_dir` | analyst/rules | Primary rules (hot-reload) |
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
| `OFDD_DATALAKE_RULES_DIR` | Rules directory (analyst/rules) |
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
