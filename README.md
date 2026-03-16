# Open-FDD

![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Development Status](https://img.shields.io/badge/status-3%20--%20Alpha-orange)
![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![BACnet](https://img.shields.io/badge/Protocol-BACnet-003366)
![TimescaleDB](https://img.shields.io/badge/TimescaleDB-compatible-FDB515?logo=timescale&logoColor=black)
![Grafana](https://img.shields.io/badge/Grafana-supported-F46800?logo=grafana&logoColor=white)
![PyPI](https://img.shields.io/pypi/v/open-fdd?color=blue&label=pypi%20version) — *PyPI package is legacy (FD equations only; no AFDD framework) and is no longer supported. Use this repo.*
[![Discord](https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white)](https://discord.gg/Ta48yQF8fC)

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
- Test paths are set in `pyproject.toml` (`open_fdd/tests`, `stack/ha_integration/tests`). Run `pytest` with no path to use them.
- Style and workflow: [docs/contributing.md](docs/contributing.md).


---


## AI and data modeling

### Overview AI agent (read-only)

On the **Overview** page, the **Overview AI assistant** lets you ask questions in natural language (e.g. “How is the HVAC running?” or “What faults are configured?”). The backend attaches live fault and sensor data (last 24h) and an excerpt of the platform docs, then calls OpenAI (you supply your API key in the UI; it is not stored). The agent answers from that context only and does not change the system. Charts and tables can be popped out and downloaded as CSV. See [docs/appendix/api_reference.md#overview-ai-context-and-behavior](docs/appendix/api_reference.md#overview-ai-context-and-behavior).

### Data model: export → enhance → re-import

You can improve the RDF data model by exporting it to JSON, enhancing it (with or without an LLM), then re-importing.

- **Without LLM (standalone):** Export the data model to JSON (frontend **Data model** page or `GET /data-model/export`), edit the JSON manually (e.g. add Brick types, equipment, feeds/fed-by), then import via the frontend or `PUT /data-model/import`. No OpenAI or other LLM calls required.
- **With LLM (AI-assisted):** Export to JSON, then use the in-app **“OpenAI API Assist”** (Tag with OpenAI) or an external LLM (e.g. ChatGPT) to tag BACnet points with Brick classes, rule inputs, and equipment. Copy the **canonical prompt** from [config/canonical_llm_prompt.txt](config/canonical_llm_prompt.txt) and the YAML files for the task; the LLM returns tagged JSON that you import back. The backend loads the prompt from `config/canonical_llm_prompt.txt` when present (fallback: built-in prompt). For **deterministic mapping** (repeatable, rules-style), see [docs/modeling/ai_assisted_tagging.md](docs/modeling/ai_assisted_tagging.md) and [docs/modeling/llm_mapping_template.yaml](docs/modeling/llm_mapping_template.yaml). For a **one-shot LLM workflow**, see [docs/modeling/llm_workflow.md](docs/modeling/llm_workflow.md).

After reviewing the HVAC system from a systems perspective, the engineer can chat with the LLM about the modeling task; the LLM adds metadata (Brick classes, feeds/fed-by). The final JSON is imported into Open-FDD and parsed into the data model.

<details>
<summary>Canonical prompt (inline copy; prefer editing <a href="config/canonical_llm_prompt.txt">config/canonical_llm_prompt.txt</a>)</summary>



</details>

The final step is for the engineer to perform robust SPARQL query testing to verify that the data model returns the exact expected responses needed to summarize the HVAC system. For example, if the site contains a VAV AHU system with chiller-based cooling, the engineer should test queries that validate the connected relationships in the model, including those needed to support control algorithms and fault detection logic.

There is a SPARQL cookbook in the documentation that can be used for this purpose. These tests should confirm that the data model returns the expected feed and fed-by relationships for the HVAC system. From there, additional SPARQL queries can be developed for algorithm-specific needs. For example, a Guideline 36 duct static pressure reset sequence may require querying for all BACnet devices and point addresses associated with VAV boxes served by a given AHU, including damper positions or commands, airflow sensor values and setpoints, and the AHU duct static pressure sensor and static pressure setpoint.

Overall, SPARQL testing should be used by the engineer to validate that the data model fully supports the optimization algorithms and fault rules planned for the site.


## The open-fdd Pyramid


If OpenFDD nails the ontology, the project will be a huge success: an open-source knowledge graph for buildings. Everything else is just a nice add-on.

![Open-FDD system pyramid](https://raw.githubusercontent.com/bbartling/open-fdd/master/OpenFDD_system_pyramid.png)

---

## Online Documentation

[📖 Docs](https://bbartling.github.io/open-fdd/) — For a copy-paste guide to run Open-FDD on Linux hardware.

---


## Dependencies

[pandas](https://github.com/pandas-dev/pandas) · [PyYAML](https://github.com/yaml/pyyaml) · [FastAPI](https://fastapi.tiangolo.com/)  

Optional: [rdflib](https://github.com/RDFLib/rdflib) (Brick TTL), [matplotlib](https://github.com/matplotlib/matplotlib) (viz)

---

## Contributing

Contributions welcome — especially bug reports, rule recipes (see the [expression rule cookbook](https://bbartling.github.io/open-fdd/expression_rule_cookbook)), BACnet integration tests, and documentation. See [docs/contributing.md](docs/contributing.md) for how to get started.

We use a **`develop`** branch for integration. Open pull requests **into `develop`**, not `master`. Branch from `develop` for your work; `master` is reserved for releases and is protected.

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

```bash
~/open-fdd$ bash scripts/bootstrap.sh --test
```

> **NOTE:** Do not open pull requests from or push to `master`. Contributions go through `develop`.


---

## License

MIT