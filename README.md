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

This repository is the **`open-fdd`** **rules engine**: YAML-defined fault detection on **pandas** `DataFrame`s (`open_fdd.engine`). The published **PyPI** wheel contains only the `open_fdd` package.

---

## Install from PyPI

```bash
pip install open-fdd
```

Examples: **[`examples/README.md`](examples/README.md)**.

Documentation: **[bbartling.github.io/open-fdd](https://bbartling.github.io/open-fdd/)** (Jekyll site under `docs/`), plus **[`docs/howto/openfdd_engine_pypi.md`](docs/howto/openfdd_engine_pypi.md)** for releases.

---

## Develop and test

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e ".[dev]"
pytest
```

---

## Dependencies

Runtime: **pandas**, **NumPy**, **PyYAML**, **pydantic** (see [`pyproject.toml`](pyproject.toml)). For **matplotlib** (notebooks) or **python-docx** (Word reports), install those separately if you use those examples.

---

## Contributing

See [TESTING.md](TESTING.md), [docs/contributing.md](docs/contributing.md), and the `open-fdd` Discord **`#dev-chat`**.

---

## License

MIT
