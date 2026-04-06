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

For the full on-prem **automated fault detection and diagnostics (AFDD)** stack—which uses the `open-fdd` engine from PyPI internally as a full Linux web application—see **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)**.

---

## Install Package from PyPi

```bash
pip install open-fdd
```

Examples: **[`examples/README.md`](https://github.com/bbartling/open-fdd/blob/master/examples/README.md)** — quick runs for **Brick / Haystack / DBO / 223P** ontologies.


---

## Documentation

* 📖 **[Engine Docs](https://bbartling.github.io/open-fdd/)** — `pip install open-fdd`, RuleRunner, YAML rules, examples
* 📕 **[PDF Docs](https://github.com/bbartling/open-fdd/blob/master/pdf/open-fdd-docs.pdf)** — prebuilt bundle in the repo (refreshed by CI when `docs/` change)
* 📗 **[AFDD Stack Docs](https://bbartling.github.io/open-fdd-afdd-stack/)** — Docker, API, BACnet, UI ([repo](https://github.com/bbartling/open-fdd-afdd-stack))

---

## Dependencies

See [`pyproject.toml`](pyproject.toml). **Dependencies:** pandas, NumPy, PyYAML, pytest. **Brick TTL → column_map** (rdflib / SPARQL) lives in **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)**, not in this wheel. For **matplotlib** (notebooks / `fault_viz`) or **python-docx** (Word reports), install those packages separately if you use those modules.

---

## Contributing

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv env && source env/bin/activate
pip install -U pip && pip install -e .
pytest
```

See also: [TESTING.md](TESTING.md), [docs/contributing.md](docs/contributing.md), and the channel on the `open-fdd` Discord for **`#dev-chat`**.

---

## License

MIT
