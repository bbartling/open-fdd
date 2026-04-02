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

## Quick Starts

### Open-FDD Engine-only (rules engine, no Docker) PyPi

If you only want the Python rules engine (without the full platform stack), you can use it in standard Python environments.

```bash
pip install open-fdd
```


### Open-FDD AFDD Platform Manually by the Human

Open-FDD uses Docker and Docker Compose to orchestrate and manage all platform services within a unified containerized environment. The bootstrap script (`./scripts/bootstrap.sh`) is **Linux-only** and intended for IoT edge applications using Docker exclusively.


**Standard HTTP bootstrap (no TLS):** Bind the DIY BACnet server to a specific OT NIC and port, while using a separate NIC for outbound internet access via DHCP.

```bash
cd /path/to/open-fdd

printf '%s' 'YourSecurePassword' | ./scripts/bootstrap.sh \
  --bacnet-address 192.168.204.16/24:47808 \
  --bacnet-instance 12345 \
  --user ben \
  --password-stdin
```

> **NOTE:** Both the DIY BACnet server and Open-FDD API in the **Standard HTTP bootstrap (no TLS)** configuration still require bearer tokens for authorization. These are defined in `open-fdd/stack/.env` and are set during the bootstrapping process.


**Standard hardened stack — self-signed TLS (Caddy) and app login:** Open-FDD runs over TLS with self-signed certificates, and there is no access to the Open-FDD API or the DIY BACnet server Docker container APIs.


```bash
cd /path/to/open-fdd

printf '%s' 'YourSecurePassword' | ./scripts/bootstrap.sh \
  --bacnet-address 192.168.204.16/24:47808 \
  --bacnet-instance 12345 \
  --user ben \
  --password-stdin \
  --caddy-self-signed
```


Also available is the **partial stack** mode: `./scripts/bootstrap.sh --mode collector`, `--mode model`, or `--mode engine`. See the `Docs` below for more information.

---


## The open-fdd Pyramid


If OpenFDD nails the ontology, the project will be a huge success: an open-source knowledge graph for buildings. Everything else is just a nice add-on.

![Open-FDD system pyramid](https://raw.githubusercontent.com/bbartling/open-fdd/master/OpenFDD_system_pyramid.png)

---

## Online Documentation

- 📖 [**Docs**](https://bbartling.github.io/open-fdd/) — GitHub Pages (Linux quick start, stack, reference).
- 📕 [**Documentation PDF**](https://github.com/bbartling/open-fdd/blob/master/pdf/open-fdd-docs.pdf) — offline, Kindle-friendly documentation
- ✨ [**LLM prompt (copy/paste template)**](https://bbartling.github.io/open-fdd/modeling/llm_workflow#copy-paste-prompt-template-recommended) — export the data model (knowledge graph) as JSON, run an **external** LLM-assisted tagging workflow outside Open‑FDD, then re-import the JSON; the backend parses it on import.
- 🤖 [**Open‑Claw / external agents**](https://bbartling.github.io/open-fdd/openclaw_integration) — `GET /model-context/docs`, `GET /mcp/manifest`, data-model export/import for your own OpenAI-compatible stack.

---


## Dependencies

Authoritative lists and version pins: [`pyproject.toml`](pyproject.toml) (`dependencies` and `[project.optional-dependencies]`).

**Core** (installed with `pip install open-fdd`): [pandas](https://github.com/pandas-dev/pandas) · [PyYAML](https://github.com/yaml/pyyaml) · [PyJWT](https://github.com/jpadilla/pyjwt) · [argon2-cffi](https://github.com/hynek/argon2-cffi) (password hashing for auth).

**Platform / API** (extras e.g. `pip install "open-fdd[platform]"` or `.[dev]` in a clone): [FastAPI](https://fastapi.tiangolo.com/) · [Uvicorn](https://www.uvicorn.org/) · [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) · [httpx](https://www.python-httpx.org/) · [python-multipart](https://github.com/Kludex/python-multipart) · [psycopg2-binary](https://github.com/psycopg/psycopg2) · [requests](https://github.com/psf/requests) · [openai](https://github.com/openai/openai-python) (optional AI client).

**Brick / SPARQL / TTL** (extra `[brick]` or bundled in `.[dev]`): [rdflib](https://github.com/RDFLib/rdflib) · [pyparsing](https://github.com/pyparsing/pyparsing) (pinned range for SPARQL compatibility).

**BACnet** (extra `[bacnet]`): [bacpypes3](https://github.com/JoelBender/bacpypes3) · [ifaddr](https://github.com/pydron/ifaddr) · httpx.

**Viz** (extra `[viz]`): [matplotlib](https://github.com/matplotlib/matplotlib).

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