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

This repository contains the Open-FDD **rules engine only**, published to PyPI via GitHub Actions as [`open-fdd`](https://pypi.org/project/open-fdd/).

For the full on-prem **automated fault detection and diagnostics (AFDD)** stack—which uses the `open-fdd` engine from PyPI internally and is a fully bootstrapped Linux web application—see **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)**.

---

## Install

```bash
pip install open-fdd
```

Examples: **[`examples/README.md`](https://github.com/bbartling/open-fdd/blob/master/examples/README.md)** — quick runs for **Brick / Haystack / DBO / 223P** naming:

```bash
python examples/column_map_resolver_workshop/run_ontology_demo.py --list
python examples/column_map_resolver_workshop/run_ontology_demo.py haystack
```

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

## Documentation


* 📖 **[Engine Docs](https://bbartling.github.io/open-fdd/)** — `pip install open-fdd`, RuleRunner, YAML rules, examples
* 📗 **[AFDD Stack Docs](https://bbartling.github.io/open-fdd-afdd-stack/)** — Docker, bootstrap, API, BACnet, UI ([repo](https://github.com/bbartling/open-fdd-afdd-stack))
* 📕 **[PDF Docs](https://github.com/bbartling/open-fdd/blob/master/pdf/open-fdd-docs.pdf)** — offline build: `python3 scripts/build_docs_pdf.py`
* ✨ **[LLM Workflow](https://bbartling.github.io/open-fdd-afdd-stack/modeling/llm_workflow#copy-paste-prompt-template-recommended)** — export → tag → import
* 🤖 **[Open-Claw](https://bbartling.github.io/open-fdd-afdd-stack/openclaw_integration)** — agents, MCP, API workflows


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
