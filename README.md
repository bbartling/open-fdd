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

**`open-fdd`** is a **pandas-first rules engine** for building science and HVAC fault detection: define checks in **YAML**, map columns on a **pandas** `DataFrame`, and run them with **`RuleRunner`** (`open_fdd.engine`). The published **PyPI** wheel contains the engine, schema, and reports modules only.

---

## Install from PyPI

```bash
pip install "open-fdd[engine]"
```

Bare import with **pandas** only: `pip install open-fdd` (add **`[engine]`** for YAML rules and `RuleRunner`).

**Rule authoring:** [Expression rule cookbook](docs/expression_rule_cookbook.md) · [Online docs](https://bbartling.github.io/open-fdd/)

---

## Quick start

```python
from open_fdd.engine import RuleRunner

runner = RuleRunner(rules_path="path/to/rules")
df_out = runner.run(df, column_map={"SAT": "supply_air_temp"})
```

---

## Develop and test

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e ".[dev]"
pytest open_fdd/tests/engine
```

See **`examples/`** for CSV-driven demos and notebooks.

---

## Optional PyPI shim

The repository also builds **`openfdd-engine`** (`packages/openfdd-engine/`), a thin re-export of `open_fdd.engine` that depends on `open-fdd`. Most users should install **`open-fdd`** directly.

---

## Dependencies

* **Python 3.10+** and `pip` — required: **pandas**; rule execution adds **PyYAML** and **pydantic** via the **`[engine]`** extra (NumPy via pandas).

---

## License

MIT
