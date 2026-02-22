# Open-FDD

![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Development Status](https://img.shields.io/badge/status-3%20--%20Alpha-orange)
![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![BACnet](https://img.shields.io/badge/Protocol-BACnet-003366)
![TimescaleDB](https://img.shields.io/badge/TimescaleDB-compatible-FDB515?logo=timescale&logoColor=black)
![Grafana](https://img.shields.io/badge/Grafana-supported-F46800?logo=grafana&logoColor=white)
![PyPI](https://img.shields.io/pypi/v/open-fdd?color=blue&label=pypi%20version)
[![Discord](https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white)](https://discord.gg/Ta48yQF8fC)

![open-fdd logo](https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png)

Open-FDD is an **open-source knowledge graph for building technology systems**, specializing in **fault detection and diagnostics (FDD) for HVAC**. It helps facilities optimize energy use and cut costs; because it runs **on-premises**, facilities never have to worry about a vendor hiking prices, going dark, or walking away with their data. The platform is an AFDD stack designed to run inside the building, behind the firewall, under the owner’s control. It transforms operational data into actionable, cost-saving insights and provides a secure integration layer that any cloud platform can use without vendor lock-in. U.S. Department of Energy research reports median energy savings of roughly 8–9% from FDD programs—meaningful annual savings depending on facility size and energy spend.

The building is modeled in a **unified graph**: Brick (sites, equipment, points), BACnet discovery RDF, platform config, and—as the project evolves—other ontologies such as ASHRAE 223P, in one semantic model queried via SPARQL and serialized to `config/data_model.ttl`.

---


## Quick Start — Open-FDD AFDD Platform

Open-FDD uses Docker and Docker Compose to orchestrate and manage all platform services within a unified containerized environment. It has been tested on Ubuntu Server and Linux Mint running on x86-based systems.

### 🚀 Platform Deployment (Docker)

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
./scripts/bootstrap.sh
```

This will start the full AFDD edge stack locally. The stack includes Grafana, TimescaleDB, and a Python rules engine built on pandas for time-series analytics; the default protocol is **BACnet** for commercial building automation data. Future releases will add other data sources such as REST/API and Modbus.

![Open-FDD system pyramid](OpenFDD_system_pyramid.png)

### Development: run unit tests

To run the test suite and formatter locally (no Docker required for tests):

```bash
cd open-fdd
python3 -m venv .venv
source .venv/bin/activate   # or: .venv/bin/activate on Windows
pip install -e ".[dev]"
pytest open_fdd/tests/ -v
```

Use the **`dev`** extra so all dependencies (pytest, black, psycopg2, pydantic-settings, FastAPI, rdflib, etc.) are installed and every test passes. If you see `ModuleNotFoundError` for `psycopg2` or `pydantic`, run pytest with the venv’s Python (e.g. `python -m pytest`) after `pip install -e ".[dev]"`. See [CONTRIBUTING.md](CONTRIBUTING.md) for styleguides.


---


## Standalone (Python + Pandas)


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

Contributions welcome — especially bug reports, rule recipes (see the [expression rule cookbook](https://bbartling.github.io/open-fdd/expression_rule_cookbook)), BACnet integration tests, and documentation. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to get started.

---

## License

MIT
