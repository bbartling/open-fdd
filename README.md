# Open-FDD

[![Discord](https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white)](https://discord.gg/Ta48yQF8fC)
![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Development Status](https://img.shields.io/badge/status-3%20--%20Alpha-orange)
![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![BACnet](https://img.shields.io/badge/Protocol-BACnet-003366)
![TimescaleDB](https://img.shields.io/badge/TimescaleDB-compatible-FDB515?logo=timescale&logoColor=black)
![Grafana](https://img.shields.io/badge/Grafana-supported-F46800?logo=grafana&logoColor=white)
![PyPI](https://img.shields.io/pypi/v/open-fdd?color=blue&label=pypi%20version) — *PyPI package is legacy (FD equations only; no AFDD framework) and is no longer supported. Use this repo.*


<div align="center">

![open-fdd logo](image.png)

</div>

Open-FDD is an open-source knowledge graph fault-detection platform for HVAC systems that helps facilities optimize their energy usage and cost-savings. Because it runs on-prem, facilities never have to worry about a vendor hiking prices, going dark, or walking away with their data. The platform is an AFDD stack designed to run inside the building, behind the firewall, under the owner’s control. It transforms operational data into actionable, cost-saving insights and provides a secure integration layer that any cloud platform can use without vendor lock-in. U.S. Department of Energy research reports median energy savings of roughly 8–9% from FDD programs—meaningful annual savings depending on facility size and energy spend.

The building is modeled in a **unified graph**: Brick (sites, equipment, points), BACnet discovery RDF, platform config, and—as the project evolves—other ontologies such as ASHRAE 223P, in one semantic model queried via SPARQL and serialized to `config/data_model.ttl`.

---


## Quick Start — Open-FDD AFDD Platform

Open-FDD uses Docker and Docker Compose to orchestrate and manage all platform services within a unified containerized environment. The bootstrap script (`./scripts/bootstrap.sh`) is **Linux only** (tested on Ubuntu Server and Linux Mint, x86; should work on ARM but is untested). Windows is not supported.

### 🚀 Platform Deployment (Docker)

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
./scripts/bootstrap.sh
```

This will start the full AFDD edge stack locally. The stack includes Grafana, TimescaleDB, and a Python rules engine built on pandas for time-series analytics; the default protocol is **BACnet** for commercial building automation data. Future releases will add other data sources such as REST/API and Modbus.


### Development: branches and tests

Work off the **`develop`** branch for day-to-day development; open feature branches from `develop` and merge back to `develop`. Releases are cut from `master`. No Docker needed for the test suite. From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```

- **`.[dev]`** installs pytest, black, aiohttp, and platform deps so the full suite (open_fdd + HA integration tests) runs.
- **`./scripts/bootstrap.sh --test`** runs frontend checks + pytest + Caddy validate; pytest includes **`test_rdflib_sparql_stack.py`**, which runs the same SPARQL path as `POST /data-model/sparql` so a broken **rdflib + pyparsing** install fails CI before you deploy.
- Test paths are set in `pyproject.toml` (`open_fdd/tests`, `stack/ha_integration/tests`). Run `pytest` with no path to use them.
- Style and workflow: [docs/contributing.md](docs/contributing.md).


> **Note:** If a `develop` branch does not exist, please request one in the `#dev-chat` channel on Discord.


---


## The open-fdd Pyramid


If OpenFDD nails the ontology, the project will be a huge success: an open-source knowledge graph for buildings. Everything else is just a nice add-on.

![Open-FDD system pyramid](https://raw.githubusercontent.com/bbartling/open-fdd/master/OpenFDD_system_pyramid.png)

---

## Online Documentation

- 📖 [**Docs**](https://bbartling.github.io/open-fdd/) — GitHub Pages (Linux quick start, stack, reference).
- 📕 [**Documentation PDF**](https://github.com/bbartling/open-fdd/blob/master/pdf/open-fdd-docs.pdf) — offline / print-friendly bundle.
- ✨ [**LLM prompt (AI-assisted tagging)**](https://github.com/bbartling/open-fdd/blob/master/pdf/canonical_llm_prompt.txt) — canonical copy-paste text; same template on [**LLM workflow**](https://bbartling.github.io/open-fdd/modeling/llm_workflow/) (docs site).

---


## Dependencies

[pandas](https://github.com/pandas-dev/pandas) · [PyYAML](https://github.com/yaml/pyyaml) · [FastAPI](https://fastapi.tiangolo.com/)  

Optional: [rdflib](https://github.com/RDFLib/rdflib) (Brick TTL), [matplotlib](https://github.com/matplotlib/matplotlib) (viz)

---

## Contributing

Contributions welcome — Please use the **`develop`** branch for integration. Open pull requests **into `develop`**, not `master`. Branch from `develop` for your work; `master` is reserved for releases and is protected. PR's to the `master` branch will be rejected.

### Syncing your fork with upstream

To bring your fork up to date with the latest `develop` from this repo:

```bash
# Add the upstream repo once (replace with this repo’s URL if you forked from another fork)
git remote add upstream https://github.com/bbartling/open-fdd.git

# Fetch upstream and update your local develop
git fetch upstream
git checkout develop
git merge upstream/develop
git push origin develop
```

Then rebase or merge `develop` into your feature branch as needed. Use `git pull --rebase upstream develop` on your branch if you prefer a linear history.

### Run unit tests before pushing to GitHub

```bash
~/open-fdd$ bash scripts/bootstrap.sh --test
```


---

## License

MIT