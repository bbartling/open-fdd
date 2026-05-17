# Open-FDD

<p align="center">
  <a href="https://discord.gg/Ta48yQF8fC"><img src="https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://github.com/bbartling/open-fdd/actions/workflows/ci.yml"><img src="https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master" alt="CI"></a>
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT">
  <img src="https://img.shields.io/badge/status-Beta-blue" alt="Beta">
  <img src="https://img.shields.io/badge/Python-%3E%3D3.10-blue?logo=python&logoColor=white" alt="Python 3.10+">
  <a href="https://pypi.org/project/open-fdd/"><img src="https://img.shields.io/pypi/v/open-fdd?label=PyPI&logo=pypi&logoColor=white" alt="PyPI"></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png" alt="open-fdd logo" width="220">
</p>

<p align="center">
  <strong>pandas-first</strong> HVAC fault detection — YAML rules via <code>open_fdd.engine</code>, summaries and charts via <code>open_fdd.reports</code>
</p>

<p align="center">
  <a href="https://bbartling.github.io/open-fdd/"><strong>Documentation</strong></a>
  &nbsp;·&nbsp;
  <a href="https://pypi.org/project/open-fdd/">PyPI</a>
</p>

---

## Install

```bash
pip install "open-fdd[engine]"
```

| Extra | Purpose |
|-------|---------|
| `[engine]` | YAML rules, `RuleRunner`, column-map resolvers |
| `[reports]` | Matplotlib plots in `open_fdd.reports` |

Bare install (`pandas` only): `pip install open-fdd`. For Word reports: `pip install python-docx`.

---

## Engine

```python
from open_fdd.engine import RuleRunner

runner = RuleRunner(rules_path="path/to/rules")
df_out = runner.run(df, column_map={"SAT": "supply_air_temp"})
```

`column_map` is any logical name → DataFrame column. Cookbook examples may use optional `brick:` labels; plain dicts work too.

---

## Reports

```python
from open_fdd.reports import summarize_fault, get_fault_events

flag = "my_rule_flag"
events = get_fault_events(df_out, flag_col=flag)
summary = summarize_fault(df_out, flag_col=flag, timestamp_col="timestamp")
```

Plots need the `[reports]` extra. See the [Reports API](https://bbartling.github.io/open-fdd/api/reports/) docs.

---

## Develop

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e ".[dev]"
pytest open_fdd/tests/engine
```

Examples live under `examples/`. Optional shim package: `openfdd-engine` (re-exports the engine); most users install **`open-fdd`** only.

---

## License

MIT
