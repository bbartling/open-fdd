---
title: Getting Started
nav_order: 3
---

# Getting Started

Install **`open-fdd`**, run the engine test suite, and try **`open_fdd.reports`** in a notebook.

---

## Install from PyPI

```bash
pip install "open-fdd[engine]"
pip install "open-fdd[reports]"   # optional: matplotlib for plots
pip install python-docx           # optional: Word reports only
```

Bare wheel (pandas only):

```bash
pip install open-fdd
```

Python **3.10+** is required.

---

## Develop from a git checkout

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e ".[dev]"
python -c "from open_fdd.engine import RuleRunner; from open_fdd import reports; print('OK')"
pytest open_fdd/tests/engine
```

Optional **agent shell** (not on PyPI): `pip install -e packages/openfdd-agent-shell`, copy `openfdd.toml.example` → `openfdd.toml`, then see **[Skills and agent shell](howto/skills_and_agent)**.

---

## Minimal engine + reports

```python
from open_fdd.engine import RuleRunner
from open_fdd.reports import summarize_fault, get_fault_events

runner = RuleRunner(rules_path="path/to/rules")
df_out = runner.run(df, column_map={"SAT": "supply_air_temp"})

flag = "my_rule_flag"
events = get_fault_events(df_out, flag_col=flag)
summary = summarize_fault(df_out, flag_col=flag, timestamp_col="timestamp")
```

Use any **`column_map`** keys you choose; example rules under **`examples/`** may use optional **`brick:`** fields — see [Column map resolvers](column_map_resolvers).

---

## Examples

See **`examples/README.md`** for CSV demos and notebooks.

---

## Where to read next

- [Expression rule cookbook](expression_rule_cookbook)
- [Engine API](api/engine)
- [Reports API](api/reports)
- [Rules overview](rules/overview)
- [Column map resolvers](column_map_resolvers)
- [How-to: engine-only IoT](howto/engine_only_iot)
- [Skills and agent shell](howto/skills_and_agent) — `openfdd.toml`, workspace, Codex (checkout only)
- [BACnet toolshed](bacnet/index) — discovery and polling CLI (`bacnet_toolshed/`)
- [Verification](howto/verification)
- [Contributing](contributing)
