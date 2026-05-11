---
title: Getting Started
nav_order: 3
---

# Getting Started

Use this page to install **`open-fdd`**, run the focused engine test suite, and find examples.

---

## Install from PyPI

Bare wheel (pandas only):

```bash
pip install open-fdd
```

YAML rules and **`RuleRunner`**:

```bash
pip install "open-fdd[engine]"
```

Python **3.10+** is required (see `requires-python` in `pyproject.toml`).

---

## Develop from a git checkout

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e ".[dev]"
python -c "from open_fdd.engine import RuleRunner; print('engine OK')"
pytest open_fdd/tests/engine
```

Optional agent shell (local package, not on the engine wheel):

```bash
pip install -e packages/openfdd-agent-shell
openfdd-agent-shell --repo-root . --dry-run --message "list selected skills"
```

---

## Examples

See **`examples/README.md`** for CSV-driven demos and notebooks. Plotting or document export may need extra packages you install in your own environment.

---

## Where to read next

- [Skills and agent shell](howto/skills_and_agent)
- [Rules overview](rules/overview)
- [Expression rule cookbook](expression_rule_cookbook)
- [Column map resolvers](column_map_resolvers)
- [Engine API](api/engine)
- [How-to: engine-only IoT](howto/engine_only_iot)
- [Contributing](contributing)
