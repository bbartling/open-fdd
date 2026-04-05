---
title: Getting Started
nav_order: 3
---

# Getting Started

This page covers **installing and using the `open-fdd` PyPI package** and **running tests** in this repository. For the **Docker AFDD platform** (Compose, `bootstrap.sh`, React UI, BACnet scrapers), use **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)** and its **[documentation site](https://bbartling.github.io/open-fdd-afdd-stack/)**.

---

## Install the library (PyPI)

**Requirements:** Python 3.9+.

```bash
pip install open-fdd
```

Optional extras (see [`pyproject.toml`](https://github.com/bbartling/open-fdd/blob/master/pyproject.toml)): `[brick]`, `[bacnet]`, `[viz]`, `[platform]` (dependency bundle aligned with stack containers), `[dev]` for contributors.

---

## Minimal usage

```python
from open_fdd import RuleRunner

runner = RuleRunner("/path/to/yaml/rules")
df_out = runner.run(df)
```

Rule YAML, column maps, and expression syntax are covered under **[Fault rules for HVAC](rules/overview)** and the **[expression rule cookbook](expression_rule_cookbook)**.

---

## Clone this repo and run tests

Contributors and CI use an editable install:

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip && pip install -e ".[dev]"
pytest open_fdd/tests/ -v --tb=short
```

See **[TESTING.md](https://github.com/bbartling/open-fdd/blob/master/TESTING.md)** for how this relates to stack integration tests.

---

## Full Docker AFDD platform

The **edge stack** is **not** in this repository. Clone the stack repo and run `scripts/bootstrap.sh`:

```bash
git clone https://github.com/bbartling/open-fdd-afdd-stack.git
cd open-fdd-afdd-stack
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh --help
```

- **Stack docs (GitHub Pages):** [bbartling.github.io/open-fdd-afdd-stack](https://bbartling.github.io/open-fdd-afdd-stack/)
- **Engine** inside stack images is installed from **PyPI** (`open-fdd`), version-pinned in `pyproject.toml` and Dockerfiles.

Partial modes (`--mode collector|model|engine|full`), Caddy, Grafana, and MCP RAG are documented there.

---

## External agentic AI (stack only)

When running the **AFDD stack**, OpenAI-compatible agents can use HTTP APIs (data-model export/import, model context docs). This **does not apply** to `pip install open-fdd` alone unless you build your own API. See **[Open‑Claw integration](openclaw_integration)** and **[API reference](appendix/api_reference)** for endpoint details in stack deployments.

---

## Prerequisites (AFDD stack operators)

If you are deploying the **Docker stack**, you need Linux, Docker, Docker Compose, Git, and (for dashboard login bootstrap) **argon2-cffi** on the host Python used by `bootstrap.sh`. Full prerequisites and troubleshooting are on the **[stack getting started](https://bbartling.github.io/open-fdd-afdd-stack/getting_started/)** page (same Markdown as `docs/getting_started.md` in the stack repo).
