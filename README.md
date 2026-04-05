# Open-FDD

[![Discord](https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white)](https://discord.gg/Ta48yQF8fC)
[![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Development Status](https://img.shields.io/badge/status-Beta-blue)
![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python&logoColor=white)
[![PyPI](https://img.shields.io/pypi/v/open-fdd?label=PyPI)](https://pypi.org/project/open-fdd/)


<div align="center">

![open-fdd logo](https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png)

</div>

This repository contains the Open-FDD **rules engine only**, published on PyPI as [`open-fdd`](https://pypi.org/project/open-fdd/).

For the full on-prem **automated fault detection and diagnostics (AFDD)** stack, which is bootstrapped on Linux, see **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)**. This stack uses the `open-fdd` engine internally (installed from PyPI) and is delivered as a fully free and open-source solution using Docker.


---

## Install

```bash
pip install open-fdd
```

See examples inside the repository:
[https://github.com/bbartling/open-fdd/tree/master/examples](https://github.com/bbartling/open-fdd/tree/master/examples)

---

## Clone & test (contributors)

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip && pip install -e ".[dev]"
pytest
```

More detail on engine-only versus AFDD stack checks: [TESTING.md](TESTING.md).

---

## Full edge stack

Use **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)** for Docker Compose, `./scripts/bootstrap.sh`, and platform Python modules under **`openfdd_stack.platform`**.

---

## The open-fdd pyramid

![Open-FDD system pyramid](https://raw.githubusercontent.com/bbartling/open-fdd/master/OpenFDD_system_pyramid.png)

---

## Documentation

- 📖 [**Engine documentation**](https://bbartling.github.io/open-fdd/) — `pip install open-fdd`, `RuleRunner`, column-map resolvers, rule YAML, examples (IoT / pandas first).
- 📗 [**AFDD stack documentation**](https://bbartling.github.io/open-fdd-afdd-stack/) — Docker Compose, `./scripts/bootstrap.sh`, data modeling, API, BACnet, React UI ([repo](https://github.com/bbartling/open-fdd-afdd-stack)).
- 📕 [**Documentation PDF**](https://github.com/bbartling/open-fdd/blob/master/pdf/open-fdd-docs.pdf) — Offline / Kindle-friendly. Build from a clone with `python3 scripts/build_docs_pdf.py` → `pdf/open-fdd-docs.pdf`.
- ✨ [**LLM prompt (copy/paste template)**](https://bbartling.github.io/open-fdd-afdd-stack/modeling/llm_workflow#copy-paste-prompt-template-recommended) — Data-model export → external LLM tagging → import (stack operators).
- 🤖 [**Open‑Claw / external agents**](https://bbartling.github.io/open-fdd-afdd-stack/openclaw_integration) — Model-context docs, MCP manifest, export/import on the deployed API.

---

## Dependencies

See [`pyproject.toml`](pyproject.toml). **Core:** pandas, PyYAML, PyJWT, argon2-cffi. **`[platform]`** adds FastAPI, Uvicorn, httpx, psycopg2-binary, etc., for parity with container images (the FastAPI app code is not in this package).

---

## Contributing

```bash
pip install -e ".[dev]"
pytest
```

Details: [docs/contributing.md](docs/contributing.md). Discord **`#dev-chat`**.

---

## License

MIT
