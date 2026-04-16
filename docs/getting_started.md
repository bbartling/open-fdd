---
title: Getting Started
nav_order: 3
---

# Getting Started

Use this page to install **`open-fdd`**, run the test suite from a checkout, and find examples.

---

## Install from PyPI

```bash
pip install open-fdd
```

Python **3.9+** is supported (see `pyproject.toml` classifiers).

---

## Develop from a git checkout

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e ".[dev]"
python -c "import open_fdd; print('open_fdd import OK')"
pytest
```

---

## Examples

See **`examples/README.md`** in the repository for CSV-driven demos, ontology examples, and notebooks. Many examples assume **`pandas`** only; optional plotting or Word output need extra packages.

---

## Where to read next

- [Rules overview](rules/overview)
- [Column map resolvers](column_map_resolvers)
- [Engine API](api/engine)
- [How-to: engine-only IoT](howto/engine_only_iot)
- [Contributing](contributing)
