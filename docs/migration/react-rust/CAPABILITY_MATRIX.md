# Capability matrix (P1-M0-02 seed)

Generated from code inventory 2026-07-31. Statuses are honest; UNKNOWN means characterize in M1.

Columns: capability_id | user scenario | owner | current API/storage | target React | target Rust | target SQL | parity class | fixture(s) | feature flag | status | deletion blocker

| capability_id | user scenario | owner | current API/storage | target React | target Rust | target SQL | parity class | fixtures | flag | status | deletion blocker |
|---|---|---|---|---|---|---|---|---|---|---|---|
| CAP-AUTH | Login / JWT session | AuthPage + central_client | /api/auth/* | AuthPage | auth.rs | NONE | EXACT | authApi + AuthPage vitest | react_ui | DONE | Thin AuthPage + Bearer sessionStorage (M5-F) |
| CAP-UPLOAD | Upload CSV/ZIP package + hostile validation | package_io, multi_zip, data_loader | /api/csv/import/* | UploadPage | routes csv_import + edge package.rs | NONE | SECURITY+EXACT | hostile_zip + package.rs tests | react_ui | DONE | Rust ingest + React upload (M4-02) |
| CAP-SITE | Building/site selection + delete site data | site_model, SitesPage | datasets + workspace paths | SitesPage (main tab after WattLab) | csv_ingest::delete_dataset + jobs::delete_jobs_for_site | NONE | EXACT | SitesPage vitest + JWT 401 delete | react_ui | DONE | Sites main tab; JWT when configured; sidebar zip upload-only |
| CAP-JOBS | Jobs CRUD archive/restore/duplicate | ui_jobs, job_store | /api/jobs* | JobsPage | jobs.rs | NONE | EXACT | UNKNOWN | react_ui | DONE | React JobsPage CRUD (M4-01) |
| CAP-MAP | Role mapping + VAV/AHU relationships | mapping_wizard, role_map, role_map_gap | /api/csv/import/package/mapping + roles + session-config | MappingPage | package.rs + session_config | NONE | EXACT | package mapping unit + MappingPage vitest | react_ui | DONE | React mapping UI (M4-03) |
| CAP-RULES | Rule catalog, tuning, run-all/selected | rule_card, central_client, Overview | /api/fdd/rules*, /api/fdd/run, session-config params | Overview Run all + left-rail Update this rule (/rules → Overview) | fdd_rules + routes | sql_rules/ | EXACT+NUMERIC | fddApi params + redirect vitest | react_ui | DONE | Run Rules tab removed; Overview + sidebar own FDD run |
| CAP-OVERVIEW | Overview metrics + equipment inventory | dashboard_contract, data_model_tree | /api/fdd/equipment, analytics/* | HomePage (Overview) | routes + analytics | analytics SQL | NUMERIC | overview vitest | react_ui | DONE | Equipment inventory + contract metrics (M5-C) |
| CAP-PLOTS | FDD plots + fault overlays | charts, rule_plot_meta, rcx_plots | /api/fdd/series, results | ReportsPage (FDD Plots) | fdd series + building-scoped confirmed_fault | SQL downsample | VISUAL+SEMANTIC | ReportsPage vitest (auto-load + fault-bottom; missing overlay fails) | react_ui | DONE | vibe19 stack; confirmed_fault last lane; site-locked |
| CAP-RCX | RCx presets and rollups | ui_rcx_tab, analytics | /api/analytics/rcx/* | RcxPage | rcx_presets.rs + historian | SQL | NUMERIC | RcxPage vitest (REQUIRED_RCX_PRESET_IDS + family order) | react_ui | DONE | Frozen 18 + valve extras; Zones-first families; Heat pump/Weather placeholders |
| CAP-WEATHER | Weather provenance + BAS vs reference | weather_resolver, open_meteo, weather_psychrometrics | UNKNOWN + weather helpers | WeatherPanel | UNKNOWN | NONE | TEMPORAL+NUMERIC | UNKNOWN | react_ui | NOT_STARTED | Python Open-Meteo client |
| CAP-METER | Metering totals/periods | metering, ui_analytics | /api/analytics/metering | MeteringPage | analytics | SQL | NUMERIC | analyticsApi + MeteringPage vitest | react_ui | DONE | Monthly kWh sum + client↔API parity (M5-C) |
| CAP-FINDINGS | Engineering findings + dispositions | eng_findings | /api/jobs/*/findings\|dispositions, /api/reports/engineering-findings | FindingsPage | jobs.rs | NONE | EXACT | findingsApi + FindingsPage vitest | react_ui | DONE | Job findings + disposition save (M5-D); FDD results on Rules |
| CAP-REPORTS | Report/artifact generation + downloads | reports, report_downloads, docx_report, tuning_report | /api/reports* | ReportsPage (artifacts) | reports routes | NONE | ARTIFACT | reportsApi vitest | react_ui | DONE | List/draft/eng-findings (M5-E); PDF/DOCX may stay ORACLE |
| CAP-WATTLAB | WattLab dump + job-native handoff | wattlab_dump, ui_wattlab_job, ui_wattlab_studio | /api/jobs/*/wattlab/handoffs | WattLabPage | jobs wattlab | NONE | ARTIFACT | WattLabPage vitest | react_ui | DONE | Handoff POST (M5-E) |
| CAP-ECM | ECM honesty / open-fdd package job UI | ui_ecm_job | PyPI open_fdd.ecm_engineering | EcmPage | UNKNOWN | NONE | ARTIFACT | UNKNOWN | react_ui | NOT_STARTED | PyPI wheel not Rust |
| CAP-ERRORS | Auth errors, empty states, long-running work | browser_session, central_client | structured errors (M2) | shell | error envelope | NONE | INTERACTION | UNKNOWN | react_ui | NOT_STARTED |  |

## Module coverage checklist (`frontend/web/`)

Every product route and API client must appear in the capability ledger and map to ≥1 capability or ORACLE-ONLY/TEST.
