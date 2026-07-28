---
name: openfdd-pypi-oracle
description: >-
  Use when changing open-fdd PyPI pandas oracle libraries: open_fdd.rules,
  analytics, reporting, extras oracle/vibe19/reporting, wheel publish, consumer
  pins. Triggers on: PyPI, open-fdd package, rules runner, analytics.core,
  reporting, oracle extra, 4.1.x.
---

# PyPI pandas oracle

## Layout

| Module | Role |
| --- | --- |
| `open_fdd.rules` | Cookbook runner / catalog / gates |
| `open_fdd.analytics` | Analytics helpers (`core`, weather, topology, …) |
| `open_fdd.reporting` | Portable reports |
| Extras | `oracle`, `reporting`, `vibe19` |

Not production FDD. Consumers: vibe19, `services/ui` lab paths, tests, notebooks.

## Agent rules

1. Prefer clean venv + wheel install over editable-only proof.
2. After API changes: bump package → **build one wheel → test that exact wheel → publish that exact wheel** → bump playground/UI pins → GHCR.
3. Shim pattern in apps: `sys.modules[__name__] = open_fdd...` for private imports.
4. Keep custom rules local to vibe19/UI (`CUSTOM-*`).
