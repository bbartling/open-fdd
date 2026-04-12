# Open-FDD AFDD stack

[![Discord](https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white)](https://discord.gg/Ta48yQF8fC)
[![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Development Status](https://img.shields.io/badge/status-Beta-blue)
![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python&logoColor=white)
[![Engine (PyPI)](https://img.shields.io/pypi/v/open-fdd?label=engine%20(PyPI))](https://pypi.org/project/open-fdd/)

<div align="center">

![open-fdd logo](https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png)

</div>

Open-FDD is an open-source knowledge graph fault-detection platform for HVAC systems that helps facilities optimize their energy usage and cost-savings. Because it runs on-prem, facilities never have to worry about a vendor hiking prices, going dark, or walking away with their data. The platform is an AFDD stack designed to run inside the building, behind the firewall, under the owner’s control. It transforms operational data into actionable, cost-saving insights and provides a secure integration layer that any cloud platform can use without vendor lock-in. U.S. Department of Energy research reports median energy savings of roughly 8–9% from FDD programs—meaningful annual savings depending on facility size and energy spend.

This directory (**`afdd_stack/`**) is the **full on-prem AFDD platform** inside the **[open-fdd monorepo](https://github.com/bbartling/open-fdd)**. Docker images install the **engine from the same checkout** (`pip install ".[stack]"` at build time); production can still pin **`open-fdd`** from PyPI inside images if you fork the Dockerfiles.


---

## Documentation


* 📖 **[Stack Docs](https://bbartling.github.io/open-fdd/)** — VOLTTRON bootstrap, legacy Docker, API, React UI
* 📘 **[Engine Docs](https://bbartling.github.io/open-fdd/)** — RuleRunner, YAML rules, pandas ([repo](https://github.com/bbartling/open-fdd), [`open-fdd` PyPI](https://pypi.org/project/open-fdd/))
* 📕 **[PDF Docs](https://github.com/bbartling/open-fdd/blob/master/pdf/open-fdd-docs.pdf)** — offline build: `python3 scripts/build_docs_pdf.py`
* ✨ **[LLM Workflow](https://bbartling.github.io/open-fdd/modeling/llm_workflow#copy-paste-prompt-template-recommended)** — export → tag → import
* 🤖 **[Open-Claw](https://bbartling.github.io/open-fdd/openclaw_integration)** — model context, HTTP/OpenAPI, API workflows

---

## Quick Starts

### Open-FDD Engine-only (rules engine, no Docker) PyPi

If you only want the Python rules engine (without the full platform stack), you can use it in standard Python environments.

```bash
pip install open-fdd
```


### VOLTTRON-first “easy button” (edge bench)

**Field BACnet** belongs on **VOLTTRON 9** (Platform Driver + BACnet Proxy), like **[vibe_code_apps_6](https://github.com/bbartling/py-bacnet-stacks-playground/tree/develop/vibe_code_apps_6)**. From the **monorepo root**:

```bash
./scripts/bootstrap.sh --help
./scripts/bootstrap.sh --doctor
./scripts/bootstrap.sh --central-lab
```

Then follow **`$HOME/volttron-docker/README.md`**: build the image, **`docker compose up`**, and mount your **`VOLTTRON_HOME`** (bootstrap can write stubs under **`~/.volttron`** first). Use **`openfdd_stack.volttron_bridge`** on the host or inside the container (run **`--print-paths`** on the host for `PYTHONPATH`) to map device topics → `external_id` for rules.

### React UI next to VOLTTRON Central (`/openfdd/`)

1. **`./scripts/bootstrap.sh --print-vcfg-hints`** — reminders for **`vcfg`** (web bind, **VolttronCentral**, **VolttronCentralPlatform**).
2. **`./scripts/bootstrap.sh --volttron-config-stub`** — optional one-time stub for `$VOLTTRON_HOME/config` when the file does not exist yet (lab defaults; override with **`OFDD_VOLTTRON_BIND_WEB`** / **`OFDD_VOLTTRON_INSTANCE_NAME`**).
3. **`./scripts/bootstrap.sh --build-openfdd-ui`** — `npm ci` + production build with **`VITE_BASE_PATH=/openfdd/`** by default.
4. **`./scripts/bootstrap.sh --write-openfdd-ui-agent-config`** — writes **`volttron_agents/openfdd_central_ui/agent-config.json`** pointing `web_root` at `frontend/dist`.
5. Install the agent from **`afdd_stack/volttron_agents/openfdd_central_ui/`** (see that folder’s **README.md**) inside the running VOLTTRON container (or mount the repo and `pip install -e` there) so the platform web server serves **`/openfdd/`** alongside **`/vc/`** for Central.

### Optional: Timescale only (Open-FDD SQL schema)

Compose no longer runs API, Caddy, BACnet, or React. For a local DB matching **`stack/sql`** migrations:

```bash
./scripts/bootstrap.sh --compose-db
# or: docker compose -f afdd_stack/stack/docker-compose.yml up -d
```

See **`legacy/README.md`**. Point a **VOLTTRON SQL historian** at `postgresql://postgres:postgres@127.0.0.1:5432/openfdd` (or use a separate DB/schema per historian `tables_def`).

### Legacy Docker: TLS, app login, ports

After **`docker compose … up`**, configure **`afdd_stack/stack/.env`** (API key, optional Phase-1 user hash, Caddy) using the **[Stack Docs](https://bbartling.github.io/open-fdd/)** — the old one-shot bootstrap flags lived in a **previous** `bootstrap.sh` revision; retrieve them with **`git log -1 -- afdd_stack/scripts/bootstrap.sh`** if you need the exact shell recipe.

### Bootstrap / doctor

```bash
./scripts/bootstrap.sh --doctor   # VOLTTRON prep checks
```

### Run tests (CI / local)

From the **monorepo root**, **`./scripts/bootstrap.sh --test`** runs **`pytest`** on `open_fdd/tests` and `afdd_stack/openfdd_stack/tests` (same paths as **`pyproject.toml`**). If **`pytest`** is missing, use a venv with **`pip install -e ".[dev]"`** or once: **`OFDD_BOOTSTRAP_INSTALL_DEV=1 ./scripts/bootstrap.sh --test`**. Optional frontend: **`OFDD_BOOTSTRAP_FRONTEND_TEST=1 ./scripts/bootstrap.sh --test`** (requires Node/npm).

Equivalent manual recipe:

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
python3 -m pytest -q
```

Parity-oriented Central + DB + FDD phases: [VOLTTRON Central and AFDD parity](https://bbartling.github.io/open-fdd/howto/volttron_central_and_parity) (published site) or **`docs/howto/volttron_central_and_parity.md`** in this repo.

---

## Python layout


Local development (co-developing engine + stack) and push to a new or existing development branch:

```bash
cd /path/to/open-fdd   # monorepo root
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
python -m pytest
```

---

## License

MIT