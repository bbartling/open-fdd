# Streamlit interaction baseline (P1-M1-03)

Machine-readable scenario index. **M1 gate:** every capability row has either a
screenshot under `evidence/screenshots/` **or** an explicit `NONVISUAL`
classification. Visual capture moves to P1-M3 once the React shell + Playwright
job exists; Streamlit screenshots are not required to close M1.

| scenario_id | capability_ids | route/section | widgets | states | viewport | evidence |
|---|---|---|---|---|---|---|
| auth_login | CAP-AUTH | Login | username, password, submit | ok, fail | desktop, narrow | NONVISUAL (M3 visual) |
| upload_clean | CAP-UPLOAD | Data / package | file_uploader | loading, success, error | desktop, narrow | NONVISUAL (M3 visual); fixture `clean_single_equip` |
| upload_hostile | CAP-UPLOAD | Data / package | file_uploader | error (validation) | desktop | NONVISUAL security; fixture `hostile_zip` |
| site_select | CAP-SITE | Sites | select, delete | ok, confirm | desktop | NONVISUAL (M3 visual) |
| jobs_list | CAP-JOBS | Jobs | select, create, archive | empty, populated | desktop, narrow | NONVISUAL (M3 visual); fixture `job_full` |
| mapping_missing | CAP-MAP | Mapping | selectboxes | warning unresolved | desktop | NONVISUAL (M3 visual); fixture `missing_role` |
| rules_run_selected | CAP-RULES | Rules | multiselect, run, sliders | progress, results, fail | desktop | NONVISUAL (M3 visual); fixture `rule_outcomes` |
| overview_metrics | CAP-OVERVIEW | Overview | metrics, inventory | empty, populated | desktop | NONVISUAL (M3 visual) |
| plots_fault_overlay | CAP-PLOTS | Plots | equipment, rule, chart | empty, overlay | desktop | NONVISUAL (M3 visual) |
| rcx_presets | CAP-RCX | RCx | presets, rollups | empty, results | desktop | NONVISUAL (M3 visual) |
| weather_provenance | CAP-WEATHER | Weather | source, compare | partial | desktop | NONVISUAL (M3 visual); fixture `partial_weather` |
| metering_totals | CAP-METER | Metering | periods, totals | empty, populated | desktop | NONVISUAL (M3 visual) |
| findings_disposition | CAP-FINDINGS | Findings | status, notes, save | conflict revision | desktop | NONVISUAL (M3 visual) |
| reports_download | CAP-REPORTS | Reports | generate, download | loading, success | desktop | NONVISUAL (M3 visual) |
| wattlab_handoff | CAP-WATTLAB | WattLab | export/handoff | success | desktop | NONVISUAL (M3 visual); fixture `wattlab_v3` |
| ecm_honesty | CAP-ECM | ECM | job UI | ok | desktop | NONVISUAL (M3 visual); PyPI oracle |
| errors_long_running | CAP-ERRORS | shell | progress, retry | permission, stale | desktop, narrow | NONVISUAL (M3 visual) |

## Capture protocol (P1-M3+)

```bash
# Playwright against Streamlit or React flag UI.
# Mask timestamps, tokens, and absolute paths before storing under
# docs/migration/react-rust/evidence/screenshots/<commit>/
```

Record commit SHA + fixture hash in `PARITY_EVIDENCE.md`.
