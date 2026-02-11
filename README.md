# Open-FDD

![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Black](https://img.shields.io/badge/code%20style-black-000000.svg)
![PyPI](https://img.shields.io/pypi/v/open-fdd?color=blue&label=pypi%20version)

![open-fdd logo](https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png)

**Open-source edge AFDD for smart buildings.** Ingest BACnet and Open-Meteo telemetry, store it in TimescaleDB, and run rule-based fault detection with Grafana and APIs. Cloud IoT platforms can integrate Open-FDD at the edge for easy setup—keep OT and FDD local instead of in your cloud. The open alternative to SkySpark; deploy behind the firewall, full control, cloud-agnostic.

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
result = runner.run(df, timestamp_col="timestamp", rolling_window=3)
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

## Documentation

[📖 Docs](https://bbartling.github.io/open-fdd/)

- [Overview](https://bbartling.github.io/open-fdd/overview)
- [Getting Started](https://bbartling.github.io/open-fdd/getting_started)
- [Concepts](https://bbartling.github.io/open-fdd/concepts/) — Points, equipment, sites
- [BACnet](https://bbartling.github.io/open-fdd/bacnet/) — Discovery, scraping
- [Rules](https://bbartling.github.io/open-fdd/rules/) — Rule types, expression cookbook
- [API Reference](https://bbartling.github.io/open-fdd/api/)

---

## Platform configuration

- **BACnet:** Scraper polls diy-bacnet-server. Set `OFDD_BACNET_SCRAPE_INTERVAL_MIN`, `OFDD_BACNET_URL`. Requires `config/bacnet_discovered.csv` or `OFDD_BACNET_SCRAPE_CSV`.
- **Weather:** Open-Meteo scraper. Set `OFDD_OPEN_METEO_LATITUDE`, `OFDD_OPEN_METEO_LONGITUDE`, `OFDD_OPEN_METEO_TIMEZONE`. Disable with `OFDD_OPEN_METEO_ENABLED=false`.
- **Rules:** `OFDD_DATALAKE_RULES_DIR` (default: analyst/rules). YAML edits apply on next FDD run (hot-reload).

Full setup and troubleshooting: **[MONOREPO_PLAN.md](MONOREPO_PLAN.md)**.

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
