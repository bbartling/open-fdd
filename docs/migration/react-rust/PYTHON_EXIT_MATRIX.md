# Python exit matrix (P1-M0-02 seed)

Disposition UNKNOWN until M1 characterization proves REPLACE / ORACLE-ONLY / DELETE-P2 / ARCHIVE-DECISION / BLOCKED.

| path | purpose | production consumers | oracle value | target owner | disposition | evidence required | deletion blocker |
|---|---|---|---|---|---|---|---|
| services/ui/streamlit_app.py | Product Streamlit entry | openfdd-ui image | behavioral reference | React SPA (Phase 2 delete) | UNKNOWN | parity + soak | default UI |
| services/ui/requirements.txt | Streamlit deps | openfdd-ui | — | web image without Streamlit | UNKNOWN | image SBOM | default UI |
| services/ui/app/agent_api.py | Local/agent helpers around UI workflows | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/agent_prerun.py | Pre-run checks before FDD | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/analytics.py | Pandas analytics helpers (oracle/UI) | services/ui | YES | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/analytics_baseline.py | Baseline analytics helpers | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/bootstrap.py | UI bootstrap / env wiring | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/browser_session.py | Streamlit browser session helpers | services/ui | MAYBE | React | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/cache.py | UI cache helpers | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/central_client.py | HTTP client to central Rust /api | services/ui | MAYBE | generated TS client | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/charts.py | Plotly chart builders | services/ui | YES | React | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/column_map_json.py | Column map JSON IO | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/config.py | UI config | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/dashboard_contract.py | Dashboard contract shapes | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/data_contract.py | Dataset/package contracts | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/data_loader.py | CSV/package load into frames | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/data_model_tree.py | Equipment/model tree UI data | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/daytypes.py | Day-type classification | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/docx_report.py | DOCX report generation | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/eng_findings.py | Engineering findings UI/API glue | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/job_store.py | Jobs thin client (central SoT) | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/load_satisfaction.py | Load satisfaction analytics | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/mapping_wizard.py | Role/column mapping wizard | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/metering.py | Metering rollups (pandas path) | services/ui | YES | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/model_seed.py | Model seed helpers | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/multi_zip.py | Multi-ZIP package handling | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/occupancy.py | Occupancy helpers | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/open_meteo.py | Open-Meteo weather fetch | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/package_io.py | Package ZIP IO / validation | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/rcx_plots.py | RCx plot builders | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/report_downloads.py | Report download helpers | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/reports.py | Report orchestration | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/role_map.py | Role map resolve/persist | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/role_map_gap.py | Role-map gap analysis | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/rule_card.py | Rule card UI helpers | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/rule_plot_meta.py | Rule plot metadata | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/rules/base.py | Rule base classes (emergency/oracle path) | services/ui (OPENFDD_ALLOW_PANDAS_FDD / custom rules) | YES | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/rules/common.py | Shared rule utilities | services/ui (OPENFDD_ALLOW_PANDAS_FDD / custom rules) | YES | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/rules/cookbook_catalog.py | Cookbook catalog shim | services/ui (OPENFDD_ALLOW_PANDAS_FDD / custom rules) | YES | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/rules/custom_boilerplate.py | Custom rule boilerplate | services/ui (OPENFDD_ALLOW_PANDAS_FDD / custom rules) | YES | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/rules/custom_registry.py | Custom rule registry | services/ui (OPENFDD_ALLOW_PANDAS_FDD / custom rules) | YES | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/rules/custom_rules.py | CUSTOM-* rule implementations | services/ui (OPENFDD_ALLOW_PANDAS_FDD / custom rules) | YES | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/rules/economizer_weather.py | Economizer weather helpers | services/ui (OPENFDD_ALLOW_PANDAS_FDD / custom rules) | YES | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/rules/operational_gate.py | Operational gate helpers | services/ui (OPENFDD_ALLOW_PANDAS_FDD / custom rules) | YES | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/rules/pid_hunting.py | PID hunting helpers | services/ui (OPENFDD_ALLOW_PANDAS_FDD / custom rules) | YES | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/rules/runner.py | Pandas rule runner (gated) | services/ui (OPENFDD_ALLOW_PANDAS_FDD / custom rules) | YES | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/rules/sensor_rate.py | Sensor rate helpers | services/ui (OPENFDD_ALLOW_PANDAS_FDD / custom rules) | YES | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/rules/sensor_rate_profiles.py | Sensor rate profiles | services/ui (OPENFDD_ALLOW_PANDAS_FDD / custom rules) | YES | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/runtime_intervals.py | Runtime interval math | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/sidecar_maps.py | Sidecar map files | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/site_model.py | Site/building model helpers | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/source_profile.py | Source profile helpers | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/sql_sources.py | SQL source references for UI | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/topology_enrich.py | Topology enrichment | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/tuning_report.py | Tuning report export | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/ui_analytics.py | Analytics Streamlit section | services/ui | MAYBE | React | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/ui_ecm_job.py | ECM job / honesty UI | services/ui | MAYBE | React | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/ui_jobs.py | Jobs Streamlit section | services/ui | MAYBE | React | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/ui_rcx_tab.py | RCx Streamlit tab | services/ui | MAYBE | React | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/ui_wattlab_job.py | WattLab job handoff UI | services/ui | MAYBE | React | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/ui_wattlab_studio.py | WattLab Studio embed/section | services/ui | MAYBE | React | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/unit_system.py | Unit system preference | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/units.py | Unit conversion helpers | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/wattlab_dump.py | WattLab dump ZIP builder | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/weather_psychrometrics.py | Psychrometric helpers | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| services/ui/app/weather_resolver.py | Weather series resolve | services/ui | MAYBE | Rust/DataFusion or React presentation | UNKNOWN | call-site + parity | UNKNOWN |
| open_fdd/ecm_engineering | ECM workbooks (PyPI) | ui_ecm_job, Jobs/MCP docs | YES (engineering) | keep PyPI; React consumes API/export | KEEP-AS-LIB | packaging tests | customer ECM path |
| open_fdd/rules | Pandas oracle | UI cookbook / emergency FDD / PyPI | YES | ORACLE-ONLY in prod images | UNKNOWN | no silent prod fallback | cookbook forever |
| open_fdd/analytics | Pandas analytics libs | UI analytics shims / PyPI | YES | DataFusion analytics API | UNKNOWN | numeric parity | UNKNOWN |
| open_fdd/reporting | Findings reporting libs | eng findings / PyPI | YES | Rust reports or ORACLE | UNKNOWN | artifact parity | UNKNOWN |
