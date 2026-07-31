# Capability matrix (P1-M0-02 seed)

Generated from code inventory 2026-07-31. Statuses are honest; UNKNOWN means characterize in M1.

Columns: capability_id | user scenario | Streamlit/Python owner | current API/storage | target React | target Rust | target SQL | parity class | fixture(s) | feature flag | status | deletion blocker

| capability_id | user scenario | Streamlit/Python owner | current API/storage | target React | target Rust | target SQL | parity class | fixtures | flag | status | deletion blocker |
|---|---|---|---|---|---|---|---|---|---|---|---|
| CAP-AUTH | Login / JWT session | services/ui/streamlit_app.py + central_client | /api/auth/* | AuthPage | auth.rs | NONE | EXACT | UNKNOWN | react_ui | NOT_STARTED | Streamlit default |
| CAP-UPLOAD | Upload CSV/ZIP package + hostile validation | package_io, multi_zip, data_loader | /api/csv/import/* | UploadPage | routes csv_import + edge package.rs | NONE | SECURITY+EXACT | hostile_zip + package.rs tests | react_ui | IN_PROGRESS | Rust ingest + React upload (M4-02); Streamlit still default |
| CAP-SITE | Building/site selection + delete site data | site_model, streamlit_app | datasets + workspace paths | SitesPage | UNKNOWN | NONE | EXACT | UNKNOWN | react_ui | NOT_STARTED | Filesystem side effects |
| CAP-JOBS | Jobs CRUD archive/restore/duplicate | ui_jobs, job_store | /api/jobs* | JobsPage | jobs.rs | NONE | EXACT | UNKNOWN | react_ui | IN_PROGRESS | React JobsPage CRUD (M4-01); Streamlit still default |
| CAP-MAP | Role mapping + VAV/AHU relationships | mapping_wizard, role_map, role_map_gap | /api/csv/import/package/mapping + roles + session-config | MappingPage | package.rs + session_config | NONE | EXACT | package mapping unit + MappingPage vitest | react_ui | IN_PROGRESS | React mapping UI (M4-03); Streamlit still default |
| CAP-RULES | Rule catalog, tuning, run-all/selected | rule_card, central_client, streamlit_app | /api/fdd/rules*, /api/fdd/run, session-config params | RulesPage | fdd_rules + routes | sql_rules/ | EXACT+NUMERIC | fddApi params + RulesPage vitest | react_ui | IN_PROGRESS | Catalog+tuning+run (M5-A); Streamlit still default |
| CAP-OVERVIEW | Overview metrics + equipment inventory | dashboard_contract, data_model_tree | /api/fdd/equipment, analytics/* | HomePage (Overview) | routes + analytics | analytics SQL | NUMERIC | overview vitest | react_ui | IN_PROGRESS | Equipment inventory + contract metrics (M5-C); Streamlit still default |
| CAP-PLOTS | FDD plots + fault overlays | charts, rule_plot_meta, rcx_plots | /api/fdd/series, results | ReportsPage (FDD Plots) | fdd series | SQL downsample | VISUAL+SEMANTIC | plotDataset + ReportsPage vitest | react_ui | IN_PROGRESS | Series dataset + SVG host (M5-B); full Plotly npm later |
| CAP-RCX | RCx presets and rollups | ui_rcx_tab, analytics | /api/analytics/rcx/* | MeteringPage (RCx stub) | analytics.rs | SQL | NUMERIC | MeteringPage rcx vitest | react_ui | IN_PROGRESS | RCx AHU stub via analytics envelope (M5-C); full presets later |
| CAP-WEATHER | Weather provenance + BAS vs reference | weather_resolver, open_meteo, weather_psychrometrics | UNKNOWN + weather helpers | WeatherPanel | UNKNOWN | NONE | TEMPORAL+NUMERIC | UNKNOWN | react_ui | NOT_STARTED | Python Open-Meteo client |
| CAP-METER | Metering totals/periods | metering, ui_analytics | /api/analytics/metering | MeteringPage | analytics | SQL | NUMERIC | analyticsApi + MeteringPage vitest | react_ui | IN_PROGRESS | Monthly kWh sum + client↔API parity (M5-C); Streamlit still default |
| CAP-FINDINGS | Engineering findings + dispositions | eng_findings | /api/jobs/*/findings|dispositions, /api/reports/engineering-findings | FindingsPage | jobs.rs | NONE | EXACT | UNKNOWN | react_ui | PARTIAL_API |  |
| CAP-REPORTS | Report/artifact generation + downloads | reports, report_downloads, docx_report, tuning_report | /api/reports* | ReportsPage | reports routes | NONE | ARTIFACT | UNKNOWN | react_ui | PARTIAL_API | DOCX may stay Python/oracle |
| CAP-WATTLAB | WattLab dump + job-native handoff | wattlab_dump, ui_wattlab_job, ui_wattlab_studio | /api/jobs/*/wattlab/handoffs | WattLabPage | jobs wattlab | NONE | ARTIFACT | UNKNOWN | react_ui | PARTIAL_API |  |
| CAP-ECM | ECM honesty / open-fdd package job UI | ui_ecm_job | PyPI open_fdd.ecm_engineering | EcmPage | UNKNOWN | NONE | ARTIFACT | UNKNOWN | react_ui | NOT_STARTED | PyPI wheel not Rust |
| CAP-ERRORS | Auth errors, empty states, long-running work | browser_session, central_client | structured errors (M2) | shell | error envelope | NONE | INTERACTION | UNKNOWN | react_ui | NOT_STARTED |  |

## Module coverage checklist (`services/ui/app/`)

Every non-test callable module must appear in Python exit matrix and map to ≥1 capability or ORACLE-ONLY/TEST.

