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



**`open-fdd`** is a **pandas-first** library for HVAC and building FDD: run YAML rules with **`open_fdd.engine`**, then summarize and chart results with **`open_fdd.reports`**. The PyPI wheel also ships **`open_fdd.schema`** (result types used by the engine).



[Online docs](https://bbartling.github.io/open-fdd/)



---



## Install from PyPI



```bash

pip install "open-fdd[engine]"

```



| Extra | Purpose |

|-------|---------|

| **`[engine]`** | YAML rules, **`RuleRunner`**, column-map resolvers (PyYAML, pydantic) |

| **`[reports]`** | Plot helpers in **`open_fdd.reports`** (matplotlib) |



Bare import: `pip install open-fdd` — **pandas** only until you add extras.



Word (`.docx`) reports need **`python-docx`** in your environment (`pip install python-docx`).



---



## Quick start — engine



```python

from open_fdd.engine import RuleRunner



runner = RuleRunner(rules_path="path/to/rules")

df_out = runner.run(df, column_map={"SAT": "supply_air_temp"})

```



**`column_map`** can be any logical name → DataFrame column. Cookbook examples often use optional **`brick:`** (or **`haystack:`**, **`223p:`**) fields on inputs; plain YAML **`column:`** names and a simple dict work too.



---



## Quick start — reports



```python

from open_fdd.reports import summarize_fault, get_fault_events, plot_fault_analytics



flag_cols = [c for c in df_out.columns if c.endswith("_flag")]

events = get_fault_events(df_out, flag_col=flag_cols[0])

summary = summarize_fault(df_out, flag_col=flag_cols[0], timestamp_col="timestamp")

# plot_fault_analytics(...)  # needs matplotlib ([reports] extra)

```



See [Reports API](https://bbartling.github.io/open-fdd/api/reports/) in the docs.



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



* **Python 3.10+** — required: **pandas**; **`[engine]`** adds PyYAML and pydantic; **`[reports]`** adds matplotlib for plots.



---



## License



MIT

