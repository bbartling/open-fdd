# Open-FDD

[![Discord](https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white)](https://discord.gg/Ta48yQF8fC)
![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Development Status](https://img.shields.io/badge/status-3%20--%20Alpha-orange)
![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![BACnet](https://img.shields.io/badge/Protocol-BACnet-003366)
![TimescaleDB](https://img.shields.io/badge/TimescaleDB-compatible-FDB515?logo=timescale&logoColor=black)
![Grafana](https://img.shields.io/badge/Grafana-supported-F46800?logo=grafana&logoColor=white)
![PyPI](https://img.shields.io/pypi/v/open-fdd?color=blue&label=pypi%20version) — *`pip install open-fdd` ships the **pandas/YAML engine** (`open_fdd.engine`) and optional extras; the **full edge stack** (Docker, BACnet, API) is built from **this repo**. Very old PyPI releases were equations-only — use **2.x** or install from source. See [PyPI how-to](docs/howto/openfdd_engine_pypi.md).*


<div align="center">

![open-fdd logo](image.png)

</div>

Open-FDD is an open-source knowledge graph fault-detection platform for HVAC systems that helps facilities optimize their energy usage and cost-savings. Because it runs on-prem, facilities never have to worry about a vendor hiking prices, going dark, or walking away with their data. The platform is an AFDD stack designed to run inside the building, behind the firewall, under the owner’s control. It transforms operational data into actionable, cost-saving insights and provides a secure integration layer that any cloud platform can use without vendor lock-in. U.S. Department of Energy research reports median energy savings of roughly 8–9% from FDD programs—meaningful annual savings depending on facility size and energy spend.

The building is modeled in a **unified graph**: Brick (sites, equipment, points), BACnet discovery RDF, platform config, and—as the project evolves—other ontologies such as ASHRAE 223P, in one semantic model queried via SPARQL and serialized to `config/data_model.ttl`.

---


## Quick Start — Open-FDD AFDD Platform Manually by the Human

Open-FDD uses Docker and Docker Compose to orchestrate and manage all platform services within a unified containerized environment. The bootstrap script (`./scripts/bootstrap.sh`) is **Linux only** (tested on Ubuntu Server and Linux Mint, x86; should work on ARM but is untested). Windows is not supported.

### 🚀 Platform Deployment (Docker)

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
./scripts/bootstrap.sh
```

This will start the full AFDD edge stack locally: TimescaleDB, API, React UI, BACnet gateway/scraper, weather and FDD loops, and more. **Grafana** and an **MQTT** broker are **optional** (`./scripts/bootstrap.sh --with-grafana`, `--with-mqtt-bridge`); see [Getting Started](docs/getting_started.md). The default protocol is **BACnet** for commercial building automation data. Future releases may add other data sources such as REST/API and Modbus.

## Quick Start — OpenClaw (agent)

Give the agent **terminal access** to a cloned repo and the **repo root** as the working directory (`cd open-fdd`). OpenClaw does not replace Docker; it runs the same entrypoints a human would:

**Split machines:** OpenClaw can run on your **Windows** (or other) PC while Open‑FDD runs on a **Linux edge host** — use **SSH** (or a remote workspace) for shell commands, and point HTTP tool calls at the edge box’s **API URL** (not `localhost` unless you tunnel). For Bearer auth, use **`OFDD_API_KEY`** from the server’s **`stack/.env`** (you only need that secret on the OpenClaw side, not the whole file). Details: [Open‑Claw integration — split setup](docs/openclaw_integration.md#1e-openclaw-on-a-different-machine-than-open-fdd-split-setup).

**First session on a fresh clone:** read **`openclaw/HANDOFF_PROTOCOL.md`**, **`openclaw/SKILL.md`**, and **`openclaw/references/testing_layers.md`** so the agent follows the in-repo lab playbook (not a separate testing repo). The old **`bbartling/open-fdd-automated-testing`** tree is **deprecated** — see **`openclaw/references/legacy_automated_testing.md`** for the path map and a README snippet to freeze that repo.

1. **Bring the stack up:** `./scripts/bootstrap.sh` (full stack by default). **Partial stack:** `./scripts/bootstrap.sh --mode collector`, `--mode model`, or `--mode engine`. **Optional RAG sidecar:** add `--with-mcp-rag` (service on **8090** after index build; see [Getting Started](docs/getting_started.md)).
2. **Host Python for `--test`:** backend pytest runs on the **host**; create a venv with `python3 -m venv .venv` and `pip install -e ".[dev]"` first (see [Development: branches and tests](#development-branches-and-tests)). `bootstrap.sh` uses `.venv/bin/python` when it exists.
3. **Run the project test matrix:** `./scripts/bootstrap.sh --test` (frontend + backend pytest + Caddy validate). Frontend checks try the `openfdd_frontend` container first, then fall back to host `npm` if container exec is restricted.

**Where to “MCP” / discover tools (HTTP, not stdio):** after services are up, the platform lists tool-shaped HTTP mappings at **`http://localhost:8000/mcp/manifest`** (Bearer **`OFDD_API_KEY`** from **`stack/.env`** when auth is enabled). If you started MCP RAG, use **`http://localhost:8090/manifest`** for that sidecar’s routes. Long-form guide: [Open‑Claw integration](docs/openclaw_integration.md).

**What to paste for OpenClaw (one line):** *Working directory: this repo root; create `.venv` and `pip install -e ".[dev]"` before `--test` if host pytest is missing; run `./scripts/bootstrap.sh` then `./scripts/bootstrap.sh --test` when asked; discover HTTP tools from `http://localhost:8000/mcp/manifest` and, if `--with-mcp-rag` was used, `http://localhost:8090/manifest`; send `Authorization: Bearer <OFDD_API_KEY>` using the value in `stack/.env`. Lab notes: `openclaw/README.md`, logs under `openclaw/logs/`.*

**One-liner — humans:** Clone the repo, `cd` into it, run `./scripts/bootstrap.sh` for the **full** stack or `./scripts/bootstrap.sh --mode collector|model|engine` for a **modular** slice, optionally add `--with-mcp-rag`, and run `./scripts/bootstrap.sh --test` to exercise the automated checks.

**One-liner — OpenClaw:** From the repo root, execute `./scripts/bootstrap.sh [--mode full|collector|model|engine] [--with-mcp-rag]` to match the desired footprint, then `./scripts/bootstrap.sh --test` to validate, and wire tool discovery to `http://localhost:8000/mcp/manifest` (and `http://localhost:8090/manifest` if RAG is running) with Bearer auth from `stack/.env`.

**OpenClaw lab (bench):** optional fake BACnet harness, SPARQL fixtures, and heavier E2E scripts live under [`openclaw/README.md`](openclaw/README.md).

### Development: branches and tests

Work off the **`develop`** branch for day-to-day development; open feature branches from `develop` and merge back to `develop`. Releases are cut from `master`. No Docker needed for the test suite. From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```

- **`.[dev]`** installs pytest, black, aiohttp, and platform deps so the full suite (open_fdd + HA integration tests) runs.
- **`./scripts/bootstrap.sh --test`** runs frontend checks + pytest + Caddy validate; frontend checks try container-first and fall back to host `npm` when needed. Pytest includes **`test_rdflib_sparql_stack.py`**, which runs the same SPARQL path as `POST /data-model/sparql` so a broken **rdflib + pyparsing** install fails CI before you deploy.
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
- ✨ [**LLM prompt (copy/paste template)**](https://bbartling.github.io/open-fdd/modeling/llm_workflow#copy-paste-prompt-template-recommended) — canonical text on the docs site (same section as [**LLM workflow**](https://bbartling.github.io/open-fdd/modeling/llm_workflow)); GitHub Pages serves this path **without** a trailing slash.

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