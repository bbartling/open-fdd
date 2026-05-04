# Open-FDD

[![Discord](https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white)](https://discord.gg/Ta48yQF8fC)
[![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Development Status](https://img.shields.io/badge/status-Beta-blue)
![Python](https://img.shields.io/badge/Python-%3E%3D3.10-blue?logo=python&logoColor=white)
[![PyPI](https://img.shields.io/pypi/v/open-fdd?label=PyPI&logo=pypi&logoColor=white&cacheSeconds=600)](https://pypi.org/project/open-fdd/)

<div align="center">

![open-fdd logo](https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png)

</div>

This repository is the **`open-fdd`** **rules engine**: YAML-defined fault detection on **pandas** `DataFrame`s (`open_fdd.engine`). The published **PyPI** wheel contains only the `open_fdd` package.

---

## Install from PyPI

```bash
pip install open-fdd
```

## Dashboard

The web dashboard is a local operator web UI (React) backed by a FastAPI bridge, MCP RAG for retrieval context, and an AI agent that uses OpenAI Codex (subscription / `codex login` auth on the bridge host), all talking to services on localhost. Codex-backed tasks help the HVAC FDD analyst because the bridge spawns the `codex` CLI as a child OS process per turn (not “Python subprocesses” in the sense of running inside the interpreter). Codex is OpenAI’s CLI product; Open-FDD starts that binary on the host and supplies flags and environment variables, while authentication, model selection, tools, and execution policy are handled by Codex itself.

**Start everything** (gateway + MCP + UI, data under `stack/local-data`):

```powershell
# Windows (from repo root)
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

```bash
# macOS, Linux, or WSL (from repo root)
bash ./scripts/start-local.sh
```

Details: **[Desktop app how-to](docs/howto/desktop_app.md)** (sections *Launch* and *MCP RAG*).

---

## Online Documentation

* 📘 **Open FDD Fault Detection Engine**
  Core rules engine with `RuleRunner`, YAML-based fault logic, and pandas workflows.
  [Documentation](https://bbartling.github.io/open-fdd/) · [GitHub](https://github.com/bbartling/open-fdd) · [PyPI](https://pypi.org/project/open-fdd/)

## Other Useful Applications

Optional companion projects for BACnet integrations and HVAC optimization workflows.

* 🔗 **DIY BACnet Server**
  Lightweight BACnet server with JSON-RPC and MQTT support for IoT integrations.
  [Documentation](https://bbartling.github.io/diy-bacnet-server/) · [GitHub](https://github.com/bbartling/diy-bacnet-server)

* ⚙️ **easy-aso Framework**
  Lightweight framework for Automated Supervisory Optimization (ASO) algorithms at the IoT edge.
  [Documentation](https://bbartling.github.io/easy-aso/) · [GitHub](https://github.com/bbartling/easy-aso) · [PyPI](https://pypi.org/project/easy-aso/0.1.7/)


---

## Develop and test

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e ".[dev]"
# if you are working on desktop UI/storage/tests:
pip install -e ".[dev,desktop]"
pytest
```

---

## Dependencies

* Python 3.10+ (see `requires-python` in `pyproject.toml`)
* `pandas`
* `numpy`
* `pyyaml`
* `pydantic>=2.4,<3`
* `pip` + virtual environment tooling (`python3 -m venv`)

---

## License

MIT
