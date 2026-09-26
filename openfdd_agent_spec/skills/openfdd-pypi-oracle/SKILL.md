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
| `open_fdd.reporting` | Portable reports, including offline `single_system_typst` |
| `open_fdd.analytics.anomaly` | `open-fdd-anomaly` screen + report CLI |
| Extras | `oracle`, `reporting`, `anomaly`, `vibe19` |

Not production FDD. Consumers: vibe19, `frontend/web` lab paths, tests, notebooks.

## Camber (external reference)

[Camber](https://github.com/yroussev/camber) (Apache-2.0) is an **external** M&V /
change-point algorithm reference for ports into `open_fdd.ecm_engineering` /
`open_fdd.analytics` (Wave S3). Prefer clean-room from standards (IPMVP / G14) or
Apache-attributed adapt with NOTICE. **Never** add Camber as a runtime dep of
`openfdd-central` / `openfdd-web`, ship OT adapters, or treat `camber serve` as
product UI. Role alias Camber↔SQL is a **doc table only** until twin SQL lands (S4).

## Agent rules

1. Prefer clean venv + wheel install over editable-only proof.
2. After API changes: bump package → **build one wheel → test that exact wheel → publish that exact wheel** → bump playground/UI pins → GHCR.
3. Shim pattern in apps: `sys.modules[__name__] = open_fdd...` for private imports.
4. Keep custom rules local to vibe19/UI (`CUSTOM-*`).
5. Camber-inspired ports stay outside the product HTTP path (this skill + ECM engineering).
6. **Chart parity (W-CHART):** React Plotly is visual SoT. Keep
   `open_fdd.analytics.charts.RAINBOW_PALETTE` + `equipment_inspection_chart`
   aligned with `frontend/web/src/api/charts.contract.json` /
   `inspectChart.ts`. Permanent tests:
   `tests/analytics/test_chart_palette_parity.py` +
   `tests/reporting/test_report_chart_palette.py` (Findings chrome bars).
   PyPI overview PNG names keep Soft-OPEN `overview_*` prefix vs React bare stems.
7. **Economizer delta scatter:** x = `delta_or_f` = OAT − RAT, y = `delta_mr_f` = MAT − RAT
   (`economizer_delta_scatter` / `build_economizer_delta_points`). Offline Typst
   reports must call that chart with `viewport="bottom_left"` (both deltas ≤ 0).
   Do not plot OAT−MAT vs RAT−MAT.
8. **Single-AHU Typst:** `open-fdd-anomaly report --month YYYY-MM`. Week RCx lines
   and fault overlays come from `charts` / `rcx_plots` / `rule_result_chart`.
   No histograms. Web OAT via column, CSV, or `open_meteo.fetch_open_meteo`.
