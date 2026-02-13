# Open-FDD

![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Black](https://img.shields.io/badge/code%20style-black-000000.svg)
![PyPI](https://img.shields.io/pypi/v/open-fdd?color=blue&label=pypi%20version)
[![Discord](https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/2ZYXJN6p)

![open-fdd logo](https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png)

Open-FDD is an open source fault detection framework for HVAC systems. Proprietary fault-detection tools for HVAC systems are costly and difficult to integrate as users must develop their own fault rules, and Open-FDD is the only out-of-the-box solution providing continuous fault detection that runs on your infrastructure with pre-defined fault rules.

Open-FDD ingests BACnet and Open-Meteo telemetry out of the box, stores it in TimescaleDB, runs prebuilt fault rules, and provides monitoring in Grafana with API access for integration — all directly at the edge.

---

## Quick start

### Platform (Docker)

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
./scripts/bootstrap.sh
```

- **Grafana:** http://localhost:3000 (admin/admin)
- **API (Swagger):** http://localhost:8000/docs
- **BACnet Swagger:** http://localhost:8080/docs (when diy-bacnet-server is running)

### Standalone (Python + Pandas)

*Pandas is Python's data analysis library and powers the open-fdd AFDD engine.* Run rules on DataFrames without the full platform:

```python
import pandas as pd
from pathlib import Path
from open_fdd.engine.runner import RuleRunner, load_rule

df = pd.DataFrame({
    "timestamp": ["2023-01-01 00:00", "2023-01-01 00:15", "2023-01-01 00:30"],
    "OAT (°F)": [45, 46, 47],
    "SAT (°F)": [55, 56, 90],
})

runner = RuleRunner(rules_path="open_fdd/rules")
result = runner.run(df, timestamp_col="timestamp", rolling_window=3, skip_missing_columns=True)
# result has fault flag columns (e.g. bad_sensor_flag)
```

---

## Stack

| Service | Port | Purpose |
|---------|------|---------|
| API | 8000 | CRUD, data-model, Swagger |
| Grafana | 3000 | Dashboards |
| TimescaleDB | 5432 | PostgreSQL |
| diy-bacnet-server | 8080 / 47808 | BACnet JSON-RPC |

---

## Online Documentation

[📖 Docs](https://bbartling.github.io/open-fdd/)

---

## Platform configuration

Open-FDD is **configuration-file driven**.
You edit one file — `platform.yaml` — to tell the system **where data comes from**, **how often to run**, and **which rules to apply**. No code changes or rebuilds are required.

### Data sources

* **BACnet devices** – Uses **[diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server)** to read live BAS points over BACnet/IP. Discovered devices and points are exported to CSV, then the scraper continuously polls their present values.
* **Weather** – Uses the free **[Open-Meteo](https://open-meteo.com/)** API to add outdoor temperature, humidity, and wind data to the time-series database for economizer and weather-dependent faults.
* **Rules** – Fault rules are simple **[YAML](https://yaml.org/)** files in `analyst/rules`. Edit a rule and it automatically applies on the next run (no restart needed).

### How it works

1. Scrape data
2. Store it in the database
3. Run fault rules on a schedule
4. View results in dashboards or the API

All behavior is controlled through `platform.yaml` (or optional `OFDD_*` environment variables for Docker/edge deployments), making the platform portable across buildings and easy to tune without touching code.

---

## Platform config example

Copy to `platform.yaml` and edit.
Environment variables (`OFDD_*`) override these values.

```yaml
# FDD rule loop: periodic runs
# Each run loads YAML rules, pulls recent history from TimescaleDB into pandas,
# evaluates faults, and writes results back to the database.

rule_interval_hours: 3    # run every 3 hours
lookback_days: 3          # historical window loaded per run
rolling_window: 6         # consecutive samples required to flag fault

# Rules: analyst overrides first (hot reload), then defaults
rules_yaml_dir: "open_fdd/rules"
datalake_rules_dir: "analyst/rules"

# Optional Brick TTL model for semantic mapping (Brick → points)
# If omitted, the system uses points.brick_type / fdd_input from the database
# brick_ttl_dir: "config"

# BACnet driver (edge scraping via diy-bacnet-server)
bacnet_enabled: true
bacnet_scrape_interval_min: 5
bacnet_config_csv: "config/bacnet_device.csv"

# Open-Meteo weather driver
open_meteo_enabled: true
open_meteo_interval_hours: 24
open_meteo_latitude: 41.88
open_meteo_longitude: -87.63
open_meteo_timezone: America/Chicago
open_meteo_days_back: 3
open_meteo_site_id: default
```

---


## Dependencies

[pandas](https://github.com/pandas-dev/pandas) · [PyYAML](https://github.com/yaml/pyyaml) · [FastAPI](https://fastapi.tiangolo.com/)  

Optional: [rdflib](https://github.com/RDFLib/rdflib) (Brick TTL), [matplotlib](https://github.com/matplotlib/matplotlib) (viz)

---

## Contributing

Contributions welcome — especially rule recipes, BACnet integration tests, and documentation. See the [expression rule cookbook](https://bbartling.github.io/open-fdd/expression_rule_cookbook) for patterns.

---

## License

MIT
