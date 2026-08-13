---
title: Pandas usage inventory (frontend/web)
parent: Architecture
nav_order: 13
---

# Pandas usage inventory (`frontend/web`)

**Audit date:** 2026-07-28 · Milestone A closeout / Milestone B input.

Production FDD execution is **DataFusion SQL** via central (`POST /api/fdd/run`).
This inventory classifies pandas / `open_fdd.rules` / `analytics` usage in the
product React SPA so agents do not confuse lab/oracle paths with production.

## Classification legend

| Class | Meaning |
|-------|---------|
| `ORACLE_ONLY` | Pandas cookbook / oracle / custom rules — allowed |
| `DISPLAY_BOUNDARY` | Charts, tables, React display — allowed |
| `PACKAGE_IO` | CSV/package/WattLab load/save — allowed |
| `REPORT_RENDERING` | DOCX/xlsx/report builders — allowed |
| `MIGRATE_TO_DATAFUSION` | Should move toward central DataFusion-first APIs over time |
| `PROHIBITED_PRODUCTION_FDD` | Must not replace SQL FDD (none identified in UI as production path) |

## Inventory

| File | Purpose | Runtime path | Class | Status | Target |
|------|---------|--------------|-------|--------|--------|
|frontend/web/app/agent_api.py|oracle/analytics helpers (lab path)|frontend/web React (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|frontend/web/app/agent_prerun.py|oracle/analytics helpers (lab path)|frontend/web React (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|frontend/web/app/analytics.py|oracle/analytics helpers (lab path); production callers → central `/api/analytics/*`|frontend/web React|MIGRATE_TO_DATAFUSION|temporary_ok|central-analytics-v1 APIs now; DataFusion SQL follow-up per family|
|frontend/web/app/analytics_baseline.py|oracle/analytics helpers (lab path); production callers → central `/api/analytics/*`|frontend/web React|MIGRATE_TO_DATAFUSION|temporary_ok|central-analytics-v1 APIs now; DataFusion SQL follow-up per family|
|frontend/web/app/cache.py|UI/lab pandas usage|frontend/web React (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|frontend/web/app/charts.py|React plots / UI tables|frontend/web React (not central FDD)|DISPLAY_BOUNDARY|approved|keep display; FDD exec via central SQL|
|frontend/web/app/column_map_json.py|CSV/package/WattLab I/O|frontend/web React (not central FDD)|PACKAGE_IO|approved|keep|
|frontend/web/app/data_contract.py|CSV/package/WattLab I/O|frontend/web React (not central FDD)|PACKAGE_IO|approved|keep|
|frontend/web/app/data_loader.py|CSV/package/WattLab I/O|frontend/web React (not central FDD)|PACKAGE_IO|approved|keep|
|frontend/web/app/data_model_tree.py|UI/lab pandas usage|frontend/web React (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|frontend/web/app/daytypes.py|UI/lab pandas usage|frontend/web React (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|frontend/web/app/docx_report.py|report rendering|frontend/web React (not central FDD)|REPORT_RENDERING|approved|open_fdd.reporting where shared|
|frontend/web/app/load_satisfaction.py|oracle/analytics helpers (lab path)|frontend/web React (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|frontend/web/app/metering.py|oracle/analytics helpers (lab path); production → `/api/analytics/metering`|frontend/web React|MIGRATE_TO_DATAFUSION|temporary_ok|central metering stub live; DF SQL follow-up|
|frontend/web/app/model_seed.py|UI/lab pandas usage|frontend/web React (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|frontend/web/app/occupancy.py|oracle/analytics helpers (lab path)|frontend/web React (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|frontend/web/app/open_meteo.py|UI/lab pandas usage|frontend/web React (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|frontend/web/app/package_io.py|CSV/package/WattLab I/O|frontend/web React (not central FDD)|PACKAGE_IO|approved|keep|
|frontend/web/app/rcx_plots.py|React plots; production series → `/api/analytics/rcx/*`|frontend/web React|MIGRATE_TO_DATAFUSION|temporary_ok|display stays; compute via central analytics|
|frontend/web/app/reports.py|report rendering|frontend/web React (not central FDD)|REPORT_RENDERING|approved|open_fdd.reporting where shared|
|frontend/web/app/role_map.py|oracle/analytics helpers (lab path)|frontend/web React (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|frontend/web/app/role_map_gap.py|oracle/analytics helpers (lab path)|frontend/web React (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|frontend/web/app/rule_card.py|React plots / UI tables|frontend/web React (not central FDD)|DISPLAY_BOUNDARY|approved|keep display; FDD exec via central SQL|
|frontend/web/app/rule_plot_meta.py|UI/lab pandas usage|frontend/web React (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|frontend/web/app/rules/__init__.py|pandas oracle / custom rule surface|frontend/web React (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|frontend/web/app/rules/base.py|pandas oracle / custom rule surface|frontend/web React (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|frontend/web/app/rules/common.py|pandas oracle / custom rule surface|frontend/web React (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|frontend/web/app/rules/cookbook_catalog.py|pandas oracle / custom rule surface|frontend/web React (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|frontend/web/app/rules/custom_boilerplate.py|pandas oracle / custom rule surface|frontend/web React (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|frontend/web/app/rules/custom_registry.py|pandas oracle / custom rule surface|frontend/web React (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|frontend/web/app/rules/custom_rules.py|pandas oracle / custom rule surface|frontend/web React (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|frontend/web/app/rules/economizer_weather.py|pandas oracle / custom rule surface|frontend/web React (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|frontend/web/app/rules/operational_gate.py|pandas oracle / custom rule surface|frontend/web React (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|frontend/web/app/rules/pid_hunting.py|pandas oracle / custom rule surface|frontend/web React (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|frontend/web/app/rules/runner.py|pandas oracle / custom rule surface|frontend/web React (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|frontend/web/app/rules/sensor_rate.py|pandas oracle / custom rule surface|frontend/web React (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|frontend/web/app/rules/sensor_rate_profiles.py|pandas oracle / custom rule surface|frontend/web React (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|frontend/web/app/runtime_intervals.py|oracle/analytics helpers; production → `/api/analytics/runtime`|frontend/web React|MIGRATE_TO_DATAFUSION|temporary_ok|central runtime Δt compute live; keep oracle for vibe19 parity|
|frontend/web/app/source_profile.py|CSV/package/WattLab I/O|frontend/web React (not central FDD)|PACKAGE_IO|approved|keep|
|frontend/web/app/sql_sources.py|SQL/DataFusion bridge helpers using pandas frames|frontend/web React (not central FDD)|MIGRATE_TO_DATAFUSION|temporary_ok|central DataFusion-first APIs|
|frontend/web/app/topology_enrich.py|oracle/analytics helpers (lab path)|frontend/web React (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|frontend/web/app/tuning_report.py|report rendering|frontend/web React (not central FDD)|REPORT_RENDERING|approved|open_fdd.reporting where shared|
|frontend/web/app/ui_rcx_tab.py|React plots; production analytics → `/api/analytics/*`|frontend/web React|MIGRATE_TO_DATAFUSION|temporary_ok|cut over to central envelopes; keep display/Plotly in UI|
|frontend/web/app/unit_system.py|UI/lab pandas usage|frontend/web React (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|frontend/web/app/wattlab_dump.py|CSV/package/WattLab I/O|frontend/web React (not central FDD)|PACKAGE_IO|approved|keep|
|frontend/web/app/weather_psychrometrics.py|oracle/analytics helpers (lab path)|frontend/web React (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|frontend/web/app/weather_resolver.py|oracle/analytics helpers (lab path)|frontend/web React (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|frontend/web/scripts/_gen_building100_openfdd_json.py|UI/lab pandas usage|frontend/web React (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|frontend/web/scripts/csv_parity_check.py|UI/lab pandas usage|frontend/web React (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|frontend/web/scripts/gen_building_openfdd_maps.py|UI/lab pandas usage|frontend/web React (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|frontend/web/scripts/gen_openfdd_building_maps.py|UI/lab pandas usage|frontend/web React (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|frontend/web/scripts/profile_wattlab_export.py|UI/lab pandas usage|frontend/web React (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|frontend/web/shared/validate_hvac_data.py|UI/lab pandas usage|frontend/web React (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|frontend/web App.tsx|React plots / UI tables|frontend/web React (not central FDD)|DISPLAY_BOUNDARY|approved|keep display; FDD exec via central SQL|

## Prohibited production FDD

No `frontend/web` module was classified as `PROHIBITED_PRODUCTION_FDD`. The UI
must continue to call central for production rule execution. Local pandas rule
runners are **oracle / lab** paths only.

## Related

- [Analytics boundary](analytics-boundary.md)
- [Milestone C analytics matrix](../migration/MILESTONE_C_ANALYTICS_MATRIX.md)
- [Milestone A closeout](../migration/MILESTONE_A_CLOSEOUT.md)
- [openfdd_agent_spec ARCHITECTURE](../../openfdd_agent_spec/ARCHITECTURE.md)
