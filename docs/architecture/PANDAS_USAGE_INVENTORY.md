---
title: Pandas usage inventory (services/ui)
parent: Architecture
nav_order: 13
---

# Pandas usage inventory (`services/ui`)

**Audit date:** 2026-07-28 · Milestone A closeout / Milestone B input.

Production FDD execution is **DataFusion SQL** via central (`POST /api/fdd/run`).
This inventory classifies pandas / `open_fdd.rules` / `analytics` usage in the
product Streamlit UI so agents do not confuse lab/oracle paths with production.

## Classification legend

| Class | Meaning |
|-------|---------|
| `ORACLE_ONLY` | Pandas cookbook / oracle / custom rules — allowed |
| `DISPLAY_BOUNDARY` | Charts, tables, Streamlit display — allowed |
| `PACKAGE_IO` | CSV/package/WattLab load/save — allowed |
| `REPORT_RENDERING` | DOCX/xlsx/report builders — allowed |
| `MIGRATE_TO_DATAFUSION` | Should move toward central DataFusion-first APIs over time |
| `PROHIBITED_PRODUCTION_FDD` | Must not replace SQL FDD (none identified in UI as production path) |

## Inventory

| File | Purpose | Runtime path | Class | Status | Target |
|------|---------|--------------|-------|--------|--------|
|services/ui/app/agent_api.py|oracle/analytics helpers (lab path)|services/ui Streamlit (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|services/ui/app/agent_prerun.py|oracle/analytics helpers (lab path)|services/ui Streamlit (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|services/ui/app/analytics.py|oracle/analytics helpers (lab path); production callers → central `/api/analytics/*`|services/ui Streamlit|MIGRATE_TO_DATAFUSION|temporary_ok|central-analytics-v1 APIs now; DataFusion SQL follow-up per family|
|services/ui/app/analytics_baseline.py|oracle/analytics helpers (lab path); production callers → central `/api/analytics/*`|services/ui Streamlit|MIGRATE_TO_DATAFUSION|temporary_ok|central-analytics-v1 APIs now; DataFusion SQL follow-up per family|
|services/ui/app/cache.py|UI/lab pandas usage|services/ui Streamlit (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|services/ui/app/charts.py|Streamlit plots / UI tables|services/ui Streamlit (not central FDD)|DISPLAY_BOUNDARY|approved|keep display; FDD exec via central SQL|
|services/ui/app/column_map_json.py|CSV/package/WattLab I/O|services/ui Streamlit (not central FDD)|PACKAGE_IO|approved|keep|
|services/ui/app/data_contract.py|CSV/package/WattLab I/O|services/ui Streamlit (not central FDD)|PACKAGE_IO|approved|keep|
|services/ui/app/data_loader.py|CSV/package/WattLab I/O|services/ui Streamlit (not central FDD)|PACKAGE_IO|approved|keep|
|services/ui/app/data_model_tree.py|UI/lab pandas usage|services/ui Streamlit (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|services/ui/app/daytypes.py|UI/lab pandas usage|services/ui Streamlit (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|services/ui/app/docx_report.py|report rendering|services/ui Streamlit (not central FDD)|REPORT_RENDERING|approved|open_fdd.reporting where shared|
|services/ui/app/load_satisfaction.py|oracle/analytics helpers (lab path)|services/ui Streamlit (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|services/ui/app/metering.py|oracle/analytics helpers (lab path); production → `/api/analytics/metering`|services/ui Streamlit|MIGRATE_TO_DATAFUSION|temporary_ok|central metering stub live; DF SQL follow-up|
|services/ui/app/model_seed.py|UI/lab pandas usage|services/ui Streamlit (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|services/ui/app/occupancy.py|oracle/analytics helpers (lab path)|services/ui Streamlit (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|services/ui/app/open_meteo.py|UI/lab pandas usage|services/ui Streamlit (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|services/ui/app/package_io.py|CSV/package/WattLab I/O|services/ui Streamlit (not central FDD)|PACKAGE_IO|approved|keep|
|services/ui/app/rcx_plots.py|Streamlit plots; production series → `/api/analytics/rcx/*`|services/ui Streamlit|MIGRATE_TO_DATAFUSION|temporary_ok|display stays; compute via central analytics|
|services/ui/app/reports.py|report rendering|services/ui Streamlit (not central FDD)|REPORT_RENDERING|approved|open_fdd.reporting where shared|
|services/ui/app/role_map.py|oracle/analytics helpers (lab path)|services/ui Streamlit (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|services/ui/app/role_map_gap.py|oracle/analytics helpers (lab path)|services/ui Streamlit (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|services/ui/app/rule_card.py|Streamlit plots / UI tables|services/ui Streamlit (not central FDD)|DISPLAY_BOUNDARY|approved|keep display; FDD exec via central SQL|
|services/ui/app/rule_plot_meta.py|UI/lab pandas usage|services/ui Streamlit (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|services/ui/app/rules/__init__.py|pandas oracle / custom rule surface|services/ui Streamlit (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|services/ui/app/rules/base.py|pandas oracle / custom rule surface|services/ui Streamlit (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|services/ui/app/rules/common.py|pandas oracle / custom rule surface|services/ui Streamlit (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|services/ui/app/rules/cookbook_catalog.py|pandas oracle / custom rule surface|services/ui Streamlit (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|services/ui/app/rules/custom_boilerplate.py|pandas oracle / custom rule surface|services/ui Streamlit (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|services/ui/app/rules/custom_registry.py|pandas oracle / custom rule surface|services/ui Streamlit (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|services/ui/app/rules/custom_rules.py|pandas oracle / custom rule surface|services/ui Streamlit (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|services/ui/app/rules/economizer_weather.py|pandas oracle / custom rule surface|services/ui Streamlit (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|services/ui/app/rules/operational_gate.py|pandas oracle / custom rule surface|services/ui Streamlit (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|services/ui/app/rules/pid_hunting.py|pandas oracle / custom rule surface|services/ui Streamlit (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|services/ui/app/rules/runner.py|pandas oracle / custom rule surface|services/ui Streamlit (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|services/ui/app/rules/sensor_rate.py|pandas oracle / custom rule surface|services/ui Streamlit (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|services/ui/app/rules/sensor_rate_profiles.py|pandas oracle / custom rule surface|services/ui Streamlit (not central FDD)|ORACLE_ONLY|approved|keep (oracle)|
|services/ui/app/runtime_intervals.py|oracle/analytics helpers; production → `/api/analytics/runtime`|services/ui Streamlit|MIGRATE_TO_DATAFUSION|temporary_ok|central runtime Δt compute live; keep oracle for vibe19 parity|
|services/ui/app/source_profile.py|CSV/package/WattLab I/O|services/ui Streamlit (not central FDD)|PACKAGE_IO|approved|keep|
|services/ui/app/sql_sources.py|SQL/DataFusion bridge helpers using pandas frames|services/ui Streamlit (not central FDD)|MIGRATE_TO_DATAFUSION|temporary_ok|central DataFusion-first APIs|
|services/ui/app/topology_enrich.py|oracle/analytics helpers (lab path)|services/ui Streamlit (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|services/ui/app/tuning_report.py|report rendering|services/ui Streamlit (not central FDD)|REPORT_RENDERING|approved|open_fdd.reporting where shared|
|services/ui/app/ui_rcx_tab.py|Streamlit plots; production analytics → `/api/analytics/*`|services/ui Streamlit|MIGRATE_TO_DATAFUSION|temporary_ok|cut over to central envelopes; keep display/Plotly in UI|
|services/ui/app/unit_system.py|UI/lab pandas usage|services/ui Streamlit (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|services/ui/app/wattlab_dump.py|CSV/package/WattLab I/O|services/ui Streamlit (not central FDD)|PACKAGE_IO|approved|keep|
|services/ui/app/weather_psychrometrics.py|oracle/analytics helpers (lab path)|services/ui Streamlit (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|services/ui/app/weather_resolver.py|oracle/analytics helpers (lab path)|services/ui Streamlit (not central FDD)|ORACLE_ONLY|temporary_ok|DataFusion analytics where production; keep oracle for vibe19 parity|
|services/ui/scripts/_gen_building100_openfdd_json.py|UI/lab pandas usage|services/ui Streamlit (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|services/ui/scripts/csv_parity_check.py|UI/lab pandas usage|services/ui Streamlit (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|services/ui/scripts/gen_building_openfdd_maps.py|UI/lab pandas usage|services/ui Streamlit (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|services/ui/scripts/gen_openfdd_building_maps.py|UI/lab pandas usage|services/ui Streamlit (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|services/ui/scripts/profile_wattlab_export.py|UI/lab pandas usage|services/ui Streamlit (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|services/ui/shared/validate_hvac_data.py|UI/lab pandas usage|services/ui Streamlit (not central FDD)|DISPLAY_BOUNDARY|temporary_ok|review in Milestone B Jobs cutover|
|services/ui/streamlit_app.py|Streamlit plots / UI tables|services/ui Streamlit (not central FDD)|DISPLAY_BOUNDARY|approved|keep display; FDD exec via central SQL|

## Prohibited production FDD

No `services/ui` module was classified as `PROHIBITED_PRODUCTION_FDD`. The UI
must continue to call central for production rule execution. Local pandas rule
runners are **oracle / lab** paths only.

## Related

- [Analytics boundary](analytics-boundary.md)
- [Milestone C analytics matrix](../migration/MILESTONE_C_ANALYTICS_MATRIX.md)
- [Milestone A closeout](../migration/MILESTONE_A_CLOSEOUT.md)
- [openfdd_agent_spec ARCHITECTURE](../../openfdd_agent_spec/ARCHITECTURE.md)
