# Open-FDD

![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Development Status](https://img.shields.io/badge/status-3%20--%20Alpha-orange)
![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![BACnet](https://img.shields.io/badge/Protocol-BACnet-003366)
![TimescaleDB](https://img.shields.io/badge/TimescaleDB-compatible-FDB515?logo=timescale&logoColor=black)
![Grafana](https://img.shields.io/badge/Grafana-supported-F46800?logo=grafana&logoColor=white)
![Black](https://img.shields.io/badge/code%20style-black-000000.svg)
![PyPI](https://img.shields.io/pypi/v/open-fdd?color=blue&label=pypi%20version)
[![Discord](https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white)](https://discord.gg/2ZYXJN6p)

![open-fdd logo](https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png)

Open-FDD is an open-source Automated Fault Detection and Diagnostics (AFDD) platform specifically designed to run inside the building, behind the firewall, under the owner’s control. It transforms operational system data into actionable cost-saving insights while providing a secure integration layer that any cloud platform can leverage without vendor lock-in. Independent U.S. Department of Energy research reports median energy savings of roughly 8–9% from FDD programs, representing meaningful annual cost reductions depending on facility size and energy spend.

---


## Quick Start — Open-FDD AFDD Platform

Open-FDD uses Docker and Docker Compose to orchestrate and manage all platform services within a unified containerized environment. It has been tested on Ubuntu Server and Linux Mint running on x86-based systems.

### 🚀 Platform Deployment (Docker)

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
./scripts/bootstrap.sh
```

This will start the full AFDD edge stack locally.

---

## 🔌 Service Endpoints

| Service                             | URL                                                      | Default Credentials |
| ----------------------------------- | -------------------------------------------------------- | ------------------- |
| **Database (TimescaleDB/Postgres)** | `localhost:5432/openfdd`                                 | postgres / postgres |
| **Grafana**                         | [http://localhost:3000](http://localhost:3000)           | admin / admin       |
| **API (Swagger UI)**                | [http://localhost:8000/docs](http://localhost:8000/docs) | —                   |
| **BACnet Server (Swagger UI)**      | [http://localhost:8080/docs](http://localhost:8080/docs) | —                   |

---

## 🔐 Reverse Proxy & Endpoint Protection (Caddy)

In production deployments, Open-FDD is intended to sit behind a Caddy reverse proxy for:

* TLS termination (HTTPS)
* Basic authentication or JWT protection
* Endpoint access control
* Secure remote access

Example production architecture:

```
Building Network
   │
   ├── Open-FDD Stack (Docker)
   │      ├── API
   │      ├── Grafana
   │      ├── TimescaleDB
   │      └── BACnet Server
   │
   └── Caddy Reverse Proxy (HTTPS + auth)
```

Caddy provides secure access to internal services without exposing raw ports externally.

For a ready-made setup with **basic auth** (default user `openfdd`, default password `xyz`), optional Caddy is in `platform/docker-compose.yml` and configured in `platform/caddy/Caddyfile`. See **[Security and Caddy bootstrap](docs/security.md)** for bootstrapping, password change, which services are unencrypted by default, hardening best practices, and optional TLS (including self-signed certs). The project defaults to non-TLS.

---

## 🏢 What This Stack Represents

This deployment runs a complete behind-the-firewall AFDD platform that:

* Ingests building telemetry (e.g., BACnet, weather)
* Stores structured time-series data
* Executes automated fault detection logic
* Exposes insights via API
* Enables vendor-neutral cloud integration

The building maintains full control of operational data while enabling secure interoperability with external analytics platforms.


---

## Platform config example

Copy to `platform.yaml` and edit.
Environment variables (`OFDD_*`) override these values.

```yaml

rule_interval_hours: 3    # run every 3 hours
lookback_days: 3          # historical window loaded per run

# Rules: put your project rules here (hot reload)
rules_dir: "analyst/rules"

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

Standalone (Python + Pandas)

Open-FDD v2 will be published to PyPI as a standalone package for CSV-based analysis or for companies that want to embed DataFrame-driven FDD into existing analytics workflows. The AFDD engine is built on Pandas, Python’s high-performance data analysis library. This enables rule execution directly on DataFrames without requiring the full Docker-based platform deployment.

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

## Online Documentation

[📖 Docs](https://bbartling.github.io/open-fdd/)

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
