---
name: openfdd-pypi-oracle
description: >-
  Use when changing open-fdd PyPI pandas oracle libraries: open_fdd.rules,
  analytics, reporting, extras oracle/vibe19/reporting, wheel publish, consumer
  pins. Triggers on: PyPI, open-fdd package, rules runner, analytics.core,
  reporting, oracle extra, 4.1.x.
---

# PyPI pandas oracle

Works with any AI agent that can read markdown skills and run the PyPI CLI. Author only under `openfdd_agent_spec/skills/`. `./scripts/openfdd_install_agent_skills.sh --sync` links that tree into vendor homes. Do not edit a copy under `.cursor/skills/`. Publishing `open-fdd` showcases AI agent RCx/FDD reporting (`open-fdd-anomaly report`) alongside the ECM guide at https://bbartling.github.io/open-fdd/ecm/

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
   (`economizer_delta_scatter` / `build_economizer_delta_points`).
   `economizer_delta_frame` is an alias of `build_economizer_delta_points`; keep
   the longer name in this package. Offline Typst reports must call that chart
   with `viewport="bottom_left"` (both deltas ≤ 0). Do not plot OAT−MAT vs RAT−MAT.
   The Typst note under that figure is `econ_scatter_caption`: damper color vs
   OA-fraction lines, damper position is not fresh-air fraction, and mild
   weather (MAT ≈ RAT ≈ OAT) shrinks the deltas.
8. **Single-AHU Typst:** the only shipped PDF command is `open-fdd-anomaly report --month YYYY-MM --compile` (`open_fdd.reporting.report_template`). Do not use `build_april_report.py` or any other out-of-tree runner. Profile `vav_ahu` selects figures from mapped roles. Other system profiles are registered stubs. History sources: device folder, Open-FDD API reader, vendor API stub.
   `report.pdf` is written when `typst` is on `PATH` (the CLI runs `typst compile`). Order is sensor
   checks, plain anomaly bullets, executive summary, week RCx lines, then
   non-SV fault overlays from `rule_result_chart`. No histograms or anomaly
   method names. Web OAT via column, CSV (`web_oa_t` included; 15-minute files
   reindex onto the BAS clock; `prefer_web_oat`), or `open_meteo.fetch_open_meteo`.
   `--week YYYY-MM-DD` pins the RCx week. April example:
   `--month 2026-04 --web-oat ./open_meteo_april.csv --week 2026-04-06`
   (8640 rows at 5 minutes, week through 2026-04-12). Do not fetch that folder in CI.
   This path does not read `/home/ben/building100_rcx_report`.

## Skill home

`openfdd_agent_spec/skills/` is the only authoring tree. Do not create a parallel copy under `.cursor/skills/`, `.claude/skills/`, `.agents/skills/`, or a home directory. Sync with [`scripts/openfdd_install_agent_skills.sh`](../../../scripts/openfdd_install_agent_skills.sh) (`--sync`, optional `--user`). Orientation: [`openfdd_agent_spec/AGENTS.md`](../../AGENTS.md) and the repo [`AGENTS.md`](../../../AGENTS.md).

## Related skills

- [`openfdd-typst-rcx-report`](../openfdd-typst-rcx-report/SKILL.md) — offline `open-fdd-anomaly report` PDF
- [`openfdd-ecm-engineering`](../openfdd-ecm-engineering/SKILL.md) — ECM workbooks on the same wheel
- [`openfdd-cookbook-parity`](../openfdd-cookbook-parity/SKILL.md) — SQL and pandas cookbook honesty
- [`openfdd-package-mapping`](../openfdd-package-mapping/SKILL.md) — mapped roles the report reads
- [`openfdd-rcx-fdd-plot-poll`](../openfdd-rcx-fdd-plot-poll/SKILL.md) — blank RCx/FDD plots
