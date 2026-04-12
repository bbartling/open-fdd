# Open-FDD

[![Discord](https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white)](https://discord.gg/Ta48yQF8fC)
[![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Development Status](https://img.shields.io/badge/status-Beta-blue)
![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python&logoColor=white)
[![PyPI](https://img.shields.io/pypi/v/open-fdd?label=PyPI&logo=pypi&logoColor=white&cacheSeconds=600)](https://pypi.org/project/open-fdd/)


<div align="center">

![open-fdd logo](https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png)

</div>

This **monorepo** holds:

- **`open_fdd/`** — the **PyPI rules engine** ([`open-fdd`](https://pypi.org/project/open-fdd/)), published from CI as the slim wheel/sdist (no stack code in the wheel).
- **`afdd_stack/`** — the on-prem **platform** (Open-FDD SQL schema in Postgres/Timescale, optional FastAPI + React from source, VOLTTRON bridge helpers). **Field BACnet/Modbus and VOLTTRON Central** run under **[volttron-docker](https://github.com/VOLTTRON/volttron-docker)** and upstream VOLTTRON, not in the slim Compose file alone. Host commands: **`scripts/bootstrap.sh`**, **`scripts/volttron-docker.sh`** (see [`scripts/README.md`](scripts/README.md)).

Containers install the engine from the copied `open_fdd` sources alongside `openfdd_stack` via `pip install ".[stack]"` at image build time.

---

## Install Package from PyPi

```bash
pip install open-fdd
```

Examples: **[`examples/README.md`](https://github.com/bbartling/open-fdd/blob/master/examples/README.md)** — quick runs for **Brick / Haystack / DBO / 223P** ontologies.


---

## Documentation


### Engine (Standalone / PyPI)

* 🛠️ **[Open-FDD Engine Docs](https://bbartling.github.io/open-fdd/)**
  RuleRunner, YAML rules, examples, and engine-only workflows

* 📕 **[Engine PDF Docs](https://github.com/bbartling/open-fdd/blob/master/pdf/open-fdd-docs.pdf)**
  Offline / Kindle-friendly version of the engine documentation

---

### Full AFDD stack (`afdd_stack/`)

* 📗 **Same repo** — [`afdd_stack/README.md`](afdd_stack/README.md), `afdd_stack/stack/docker-compose.yml`, `./scripts/bootstrap.sh`
* 💻 **Docs** — [bbartling.github.io/open-fdd](https://bbartling.github.io/open-fdd/) (Jekyll site includes engine + platform guides in `docs/`)

### Bootstrap (from repo root)

**Why `docker ps` shows Timescale but not VOLTTRON Central:** `afdd_stack/stack/docker-compose.yml` starts **`db`** as **`openfdd_timescale`** (and optional profiles). **VOLTTRON Central is a separate upstream stack:** **[volttron-docker](https://github.com/VOLTTRON/volttron-docker)** is cloned next to this repo (default **`$HOME/volttron-docker`**). Open-FDD does **not** live inside that tree; use **`./scripts/volttron-docker.sh`** to run **`docker compose`** there so you never treat the PNNL checkout as part of Open-FDD.

**Current bootstrap (VOLTTRON Central path):**

```bash
cd open-fdd

./scripts/bootstrap.sh --doctor
# One-shot: local Timescale + VOLTTRON_HOME stubs + clone volttron-docker + schema check
./scripts/bootstrap.sh --central-lab

# Build the image first if needed — see volttron-docker README (“Advanced Usage” for VOLTTRON_HOME bind-mount).
./scripts/volttron-docker.sh up -d
./scripts/volttron-docker.sh ps
```

Then open **VOLTTRON Central** in a browser per upstream docs (default layout is often **`https://<host>:8443/vc/`** when the sample `platform_config.yml` uses HTTPS on 8443). Optional **Open-FDD UI next to Central:** build with `VITE_BASE_PATH=/openfdd/`, run `./scripts/bootstrap.sh --write-openfdd-ui-agent-config`, install **`openfdd_central_ui`** inside the container — see [`afdd_stack/volttron_agents/openfdd_central_ui/README.md`](afdd_stack/volttron_agents/openfdd_central_ui/README.md).

**Docs:** [Getting started](docs/getting_started.md) · [VOLTTRON Central and AFDD parity](docs/howto/volttron_central_and_parity.md) · [Open Claw + SSH operator notes](docs/openclaw_integration.md) (section 1f).

**Historical (removed from `bootstrap.sh`):** Flags like **`--bacnet-address`**, **`--caddy-self-signed`**, **`--password-stdin`** belonged to the old all-in-one Compose stack. They are **not** available in the current script. What changed: [`afdd_stack/legacy/README.md`](afdd_stack/legacy/README.md).

### Validate services

- **Timescale / Open-FDD schema:** with the DB container up, use `psql` or `docker exec` as in [`docs/getting_started.md`](docs/getting_started.md).
- **FastAPI health** (`curl http://127.0.0.1:8000/health`): only after you run **uvicorn** from source — the default Compose file does **not** start an API container.
- **VOLTTRON:** `docker logs volttron1` (or your compose service name) if the platform container exits during first boot. If you see **`DuplicateOptionError: ... web-ssl-cert`**, run **`./scripts/bootstrap.sh --central-lab`** again (or **`--volttron-config-stub`**) — it quarantines a broken **`$VOLTTRON_HOME/config`** with duplicate **`web-ssl-*`** lines and rewrites the stub. Then **`./scripts/volttron-docker.sh down`**, **`docker rm -f volttron1`**, **`./scripts/volttron-docker.sh up -d`** so first-boot **`setup-platform.py`** can finish. Set **`OFDD_VOLTTRON_CONFIG_STRICT=1`** to disable auto-quarantine.

---

## Dependencies

See [`pyproject.toml`](pyproject.toml). **Engine runtime:** pandas, NumPy, PyYAML, pydantic. **Contributors / CI:** `pip install -e ".[dev]"` installs **pytest**, **stack** dependencies (FastAPI, rdflib, …), and tooling. **`pip install open-fdd`** from PyPI stays engine-only. **Brick TTL → column_map** (rdflib / SPARQL) lives under **`afdd_stack/openfdd_stack/`**, not in the published wheel. For **matplotlib** (notebooks / `fault_viz`) or **python-docx** (Word reports), install those packages separately if you use those modules.

---

## Contributing

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv env && source env/bin/activate
pip install -U pip && pip install -e ".[dev]"
python -m pytest
```

See also: [TESTING.md](TESTING.md), [docs/contributing.md](docs/contributing.md), and the channel on the `open-fdd` Discord for **`#dev-chat`**.

---

## License

MIT
