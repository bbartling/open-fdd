---
title: Contributing
nav_order: 14
---

# Contributing

Open-FDD is in **Alpha**. We welcome bug reports, FDD rules, documentation improvements, and code contributions. The full guide (code of conduct, styleguides, PR process) is in the repository: **[CONTRIBUTING.md](https://github.com/bbartling/open-fdd/blob/master/CONTRIBUTING.md)**.

---

## How to contribute

| What | Where |
|------|--------|
| **Bugs** | [GitHub issues](https://github.com/bbartling/open-fdd/issues) — include steps to reproduce, versions, and stack trace if applicable. |
| **FDD rules** | [Expression Rule Cookbook](expression_rule_cookbook) and YAML under `analyst/rules/` — we especially want contributions from mechanical engineers and building professionals. |
| **Docs** | This site’s source lives in the repo under `docs/`; fix typos, add examples, or clarify steps and open a PR. |
| **Code** | See CONTRIBUTING.md for setup, styleguides (Black, YAML), and “good first issue” / “help wanted” labels. |

---

## Project phases and where we need help

**Alpha** (current) focuses on **platform stability**, **driver implementation** beyond BACnet, and **API changes** for specific integration needs. Contributions that help most right now:

- **Bug reports and reproduction steps** so we can harden the platform.
- **Drivers and ingest** for protocols or data sources besides BACnet (e.g. Modbus, MQTT, vendor APIs).
- **API feedback and PRs** that improve the REST surface for cloud vendors, Cx tools, and FDD workflows.

**Beta** (planned) will emphasize **data modeling** in Brick (including concepts from standards such as ASHRAE 223P), **mechanical engineering and consulting input** into the Expression Rule Cookbook, and **better default Grafana dashboards** for simple HVAC analytics. If you work in MEP or building analytics and want to contribute rules or dashboards, we’d like to hear from you—and the cookbook is the place to start.

---

## Dev lifecycle (branching, version bump, clean rebuild)

Useful when starting a new dev branch (e.g. after tagging a release on `master`) or when you want a clean Docker rebuild.

### 1. Create the dev branch and commit the version bump

From repo root (e.g. `~/open-fdd`):

```bash
cd /home/ben/open-fdd   # or your clone path

# Create and switch to dev branch (from current master)
git checkout -b dev/2.0.1

# Bump version in pyproject.toml and open_fdd/platform/config.py, then:
git add pyproject.toml open_fdd/platform/config.py
git commit -m "Bump version to 2.0.1"
```

Push the branch when ready: `git push -u origin dev/2.0.1`.

### 2. Nuclear Docker cleanup (then rebuild)

**Option A — Only this project** (recommended if you have other Docker work):

```bash
cd platform
docker compose down -v
docker compose build --no-cache
cd ..
./scripts/bootstrap.sh --build
```

**Option B — Full system prune** (removes all unused containers, images, networks, and volumes on the host; use only if this machine is dedicated to open-fdd or you are okay wiping other Docker data):

```bash
cd platform
docker compose down -v
docker system prune -a -f --volumes
cd ..
./scripts/bootstrap.sh --build
```

Bootstrap will build images, run DB migrations from `platform/sql/`, and start the stack.

---

## Quick links

- [CONTRIBUTING.md](https://github.com/bbartling/open-fdd/blob/master/CONTRIBUTING.md) — full contributing guide (conduct, reporting bugs, suggesting enhancements, rules, styleguides, commit messages).
- [Fault rules overview](rules/overview) — where rules live and how they’re loaded.
- [Expression Rule Cookbook](expression_rule_cookbook) — how to write and contribute expression-type FDD rules.
