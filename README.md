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

This repository is the Open-FDD **rules engine**, published on PyPI as [`open-fdd`](https://pypi.org/project/open-fdd/). You describe faults in YAML and run detection on pandas through `open_fdd.engine`. The same package provides `open_fdd.schema`, `open_fdd.reports`, an optional `openfdd_engine` import shim for older code, and notebooks and workshops under `examples/`.

The full on-prem **AFDD platform**—Docker Compose, FastAPI, BACnet and weather scrapers, React UI, and `bootstrap.sh`—lives in **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)**. That repo installs this engine from PyPI and ships platform code as `openfdd_stack.platform`.

---

## Install

```bash
pip install open-fdd
```

```python
from open_fdd import RuleRunner
runner = RuleRunner("/path/to/rules")
df_out = runner.run(df)
```

Extras: **`[brick]`**, **`[platform]`** (dependency bundle aligned with stack containers), **`[bacnet]`**, **`[viz]`**, **`[dev]`** for contributors. See [`pyproject.toml`](pyproject.toml).

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

- [**GitHub Pages (engine & concepts)**](https://bbartling.github.io/open-fdd/) — library, rules, modeling; some pages describe the full stack and point at **`openfdd_stack.platform`** (AFDD repo).
- [**Documentation PDF**](https://github.com/bbartling/open-fdd/blob/master/pdf/open-fdd-docs.pdf)
- [**LLM workflow template**](https://bbartling.github.io/open-fdd/modeling/llm_workflow#copy-paste-prompt-template-recommended)

**Stack-only docs** (Compose, API operations) are maintained in the **open-fdd-afdd-stack** repository.

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
