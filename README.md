# Open-FDD

[![Discord](https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white)](https://discord.gg/Ta48yQF8fC)
[![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Development Status](https://img.shields.io/badge/status-Beta-blue)
![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python&logoColor=white)
![BACnet](https://img.shields.io/badge/Protocol-BACnet-003366)
![TimescaleDB](https://img.shields.io/badge/TimescaleDB-compatible-FDB515?logo=timescale&logoColor=black)
![Grafana](https://img.shields.io/badge/Grafana-supported-F46800?logo=grafana&logoColor=white)
[![PyPI](https://img.shields.io/pypi/v/open-fdd?label=PyPI)](https://pypi.org/project/open-fdd/)


<div align="center">

![open-fdd logo](https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png)

</div>

Open-FDD is an open-source knowledge graph fault-detection platform for HVAC systems that helps facilities optimize their energy usage and cost-savings. Because it runs on-prem, facilities never have to worry about a vendor hiking prices, going dark, or walking away with their data. The platform is an AFDD stack designed to run inside the building, behind the firewall, under the owner’s control. It transforms operational data into actionable, cost-saving insights and provides a secure integration layer that any cloud platform can use without vendor lock-in. U.S. Department of Energy research reports median energy savings of roughly 8–9% from FDD programs—meaningful annual savings depending on facility size and energy spend.

The building is modeled in a **unified graph**: Brick (sites, equipment, points), BACnet discovery RDF, platform config, and—as the project evolves—other ontologies such as ASHRAE 223P, in one semantic model queried via SPARQL and serialized to `config/data_model.ttl`.

---


## Quick Start — Open-FDD AFDD Platform Manually by the Human

Open-FDD uses Docker and Docker Compose to orchestrate and manage all platform services within a unified containerized environment. The bootstrap script (`./scripts/bootstrap.sh`) is **Linux only** (maintainers primarily test Ubuntu Server and Linux Mint on **x86_64**; CI is x86_64). **ARM64** (e.g. Raspberry Pi 4/5) is not covered by CI but is used in the community—validate image availability and sizing (RAM/CPU) for Postgres + services. Windows is not supported.

### Engine-only (rules engine, no Docker)

If you only want the Python rules engine (no full platform stack):

```bash
pip install open-fdd
```

Then run the standalone examples from:

- https://github.com/bbartling/open-fdd/tree/master/examples

### 🚀 Platform Deployment (Docker)

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
./scripts/bootstrap.sh
```

**Standard full-stack bootstrap with self-signed TLS (Caddy) and app login:** uses **JWT** and **`Authorization: Bearer`**.

```bash
printf '%s' 'YOUR_PASSWORD' | ./scripts/bootstrap.sh --user YOURNAME --password-stdin --caddy-self-signed
```

Also available is the **partial stack** mode: `./scripts/bootstrap.sh --mode collector`, `--mode model`, or `--mode engine`. See [Modular architecture](docs/modular_architecture.md) for the service matrix and mode behavior.

---


## The open-fdd Pyramid


If OpenFDD nails the ontology, the project will be a huge success: an open-source knowledge graph for buildings. Everything else is just a nice add-on.

![Open-FDD system pyramid](https://raw.githubusercontent.com/bbartling/open-fdd/master/OpenFDD_system_pyramid.png)

---

## Online Documentation

- 📖 [**Docs**](https://bbartling.github.io/open-fdd/) — GitHub Pages (Linux quick start, stack, reference).
- 📕 [**Documentation PDF**](https://github.com/bbartling/open-fdd/blob/master/pdf/open-fdd-docs.pdf) — offline / print-friendly bundle (local clone: `pdf/open-fdd-docs.pdf`; build with `python3 scripts/build_docs_pdf.py` if missing).
- ✨ [**LLM prompt (copy/paste template)**](https://bbartling.github.io/open-fdd/modeling/llm_workflow#copy-paste-prompt-template-recommended) — canonical text on the docs site (same section as [**LLM workflow**](https://bbartling.github.io/open-fdd/modeling/llm_workflow)); GitHub Pages serves this path **without** a trailing slash.
- 🤖 [**Open‑Claw / external agents**](https://bbartling.github.io/open-fdd/openclaw_integration) — `GET /model-context/docs`, `GET /mcp/manifest`, data-model export/import for your own OpenAI-compatible stack.

---


## Dependencies

[pandas](https://github.com/pandas-dev/pandas) · [PyYAML](https://github.com/yaml/pyyaml) · [FastAPI](https://fastapi.tiangolo.com/)  

Optional: [rdflib](https://github.com/RDFLib/rdflib) (Brick TTL), [matplotlib](https://github.com/matplotlib/matplotlib) (viz)

---

## Contributing

Open PRs against the **current integration branch** (e.g. **`develop`** or **`develop/vX.Y.Z`**), not **`master`** — **`master`** is release-only and protected.

**Tests:** `./scripts/bootstrap.sh --test` (frontend + pytest + Caddy; frontend tries Docker then host `npm`), or from repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```

**`.[dev]`** pulls in the full Python test deps; `pyproject.toml` sets default test paths. More detail: [docs/contributing.md](docs/contributing.md). Ask in **`#dev-chat`** on Discord if the active integration branch is unclear.

**Fork sync** (once add `upstream`, then as needed):

```bash
git remote add upstream https://github.com/bbartling/open-fdd.git
git fetch upstream && git checkout develop && git merge upstream/develop && git push origin develop
```

(Use your real integration branch name instead of `develop` if the project is on a versioned line.)

---

## License

MIT