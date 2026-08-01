# Phase 2 deletion candidates (enumerated, not executed)

Generated at P1-M6-01. **Do not delete** in Phase 1. Each row becomes a bounded
Prompt 6 / Prompt 7 PR after cutover gates.

| candidate PR | paths (leaf → inward) | prerequisite |
|---|---|---|
| P2-DEL-01 UI analytics twin | `services/ui/app/analytics.py`, `analytics_baseline.py`, `ui_analytics.py`, `metering.py`, `load_satisfaction.py`, `runtime_intervals.py` | **Bundle into Prompt 7** (P2-M5 closeout) |
| P2-DEL-02 UI FDD/plots twin | `charts.py`, `rcx_plots.py`, `rule_plot_meta.py`, `rule_card.py`, `ui_rcx_tab.py` | Bundle into Prompt 7 |
| P2-DEL-03 UI jobs/findings/reports twin | `ui_jobs.py`, `job_store.py`, `eng_findings.py`, `reports.py`, `report_downloads.py`, `tuning_report.py` | Bundle into Prompt 7 |
| P2-DEL-04 UI mapping/upload twin | `mapping_wizard.py`, `role_map*.py`, `package_io.py`, `multi_zip.py`, `data_loader.py` | Bundle into Prompt 7 |
| P2-DEL-05 UI WattLab/ECM twin | `ui_wattlab_*.py`, `wattlab_dump.py`, `ui_ecm_job.py` | Bundle into Prompt 7; ECM lib KEEP-AS-LIB |
| P2-DEL-06 weather oracle relocate | `open_meteo.py`, `weather_*.py` (UI copies) | Relocate in Prompt 7; keep `open_fdd` oracle |
| P2-DEL-07 Streamlit product removal | `streamlit_app.py`, `services/ui/requirements.txt`, `openfdd-ui` image/compose | **Next PR** after P2-M5 closeout |
| P2-DEL-08 pandas FDD gate removal | `services/ui/app/rules/**`, `OPENFDD_ALLOW_PANDAS_FDD` | Prod images only; oracle retained |

Preserve: `open_fdd/ecm_engineering` (KEEP-AS-LIB), `tools/react_parity/**` oracle exporters, cookbook fixtures.
