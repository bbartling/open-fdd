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

## Quick links

- [CONTRIBUTING.md](https://github.com/bbartling/open-fdd/blob/master/CONTRIBUTING.md) — full contributing guide (conduct, reporting bugs, suggesting enhancements, rules, styleguides, commit messages).
- [Fault rules overview](rules/overview) — where rules live and how they’re loaded.
- [Expression Rule Cookbook](expression_rule_cookbook) — how to write and contribute expression-type FDD rules.
