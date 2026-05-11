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

This repository ships the **`open-fdd`** **rules engine**: YAML-defined fault detection on **pandas** `DataFrame`s (`open_fdd.engine`). The published **PyPI** wheel contains only engine and schema modules.

Operator dashboards, HTTP bridges, ingest drivers, and deployment stacks are **not** bundled. Describe what you need in `openfdd.toml`, then use **`skills/`** and the local **agent shell** to generate code under `workspace/`.

---

## Install from PyPI

```bash
pip install "open-fdd[engine]"
```

Bare import with **pandas** only: `pip install open-fdd` (add **`[engine]`** for YAML rules and `RuleRunner`).

Rule authoring: [Expression rule cookbook](docs/expression_rule_cookbook.md).

---

## Build with skills + agent shell

1. Copy `openfdd.toml.example` to `openfdd.toml` and set `[build]` targets, drivers, auth, and deploy mode.
2. Install the shell (local only, not on the engine wheel):

```bash
cd packages/openfdd-agent-shell
pip install -e ".[dev]"
```

3. From the repo root:

```bash
openfdd-agent-shell --repo-root .
```

The shell loads [AGENTS.md](AGENTS.md), selected skill recipes under [skills/](skills/), and launches **Codex CLI** to scaffold only what the manifest requests. Generated apps live in `workspace/`.

---

## Online documentation

* **Open FDD fault detection engine** — `RuleRunner`, YAML rules, pandas workflows.
  [Documentation](https://bbartling.github.io/open-fdd/) · [GitHub](https://github.com/bbartling/open-fdd) · [PyPI](https://pypi.org/project/open-fdd/)

Historical desktop/MCP how-tos under `docs/howto/` describe the retired monolith; new integrations should follow `skills/`.

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

Optional shim package:

```bash
cd packages/openfdd-engine && pip install -e .
```

---

## Dependencies

* **Python 3.10+** and `pip` — required: **pandas**; rule execution adds **PyYAML** and **pydantic** via the **`[engine]`** extra (NumPy via pandas).
* **Codex CLI** on PATH when using the agent shell (`codex` by default).
* **Node.js** only if a generated dashboard skill scaffolds a Vite/React app under `workspace/`.

---

## License

MIT
