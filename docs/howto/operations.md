---
title: Operations
parent: How-to guides
nav_order: 40
nav_exclude: true
---

# Operations

This repository ships the **`open_fdd`** **library** only. **Scheduling**, **databases**, and **HTTP APIs** are **your** operational concern.

---

## Releases and CI

- **`pytest`** on `open_fdd/tests` runs on every PR (see `.github/workflows/ci.yml`).
- PyPI publishes the **`open-fdd`** wheel from tags per [PyPI releases](openfdd_engine_pypi).

---

## Running rules on a cadence

Typical patterns:

- **Cron** or **systemd timers** calling a small Python entrypoint that loads CSV/SQL, builds a DataFrame, and runs **`RuleRunner`**.
- **Workflow engines** (Airflow, Dagster, …) with a task that imports **`open_fdd`**.

---

## See also

- [Verification](verification)
- [Engine-only / IoT](engine_only_iot)
- [Testing plan](../operations/testing_plan)
