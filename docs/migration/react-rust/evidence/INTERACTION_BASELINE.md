# Streamlit interaction baseline (P1-M1-03)

Machine-readable scenario index. Screenshots are captured later with a documented
command once a display/CI runner is available; rows marked NONVISUAL need no image.

| scenario_id | capability_ids | route/section | widgets | states | viewport | evidence |
|---|---|---|---|---|---|---|
| auth_login | CAP-AUTH | Login | username, password, submit | ok, fail | desktop, narrow | NONVISUAL until capture |
| upload_clean | CAP-UPLOAD | Data / package | file_uploader | loading, success, error | desktop, narrow | TBD screenshot |
| upload_hostile | CAP-UPLOAD | Data / package | file_uploader | error (validation) | desktop | NONVISUAL security |
| jobs_list | CAP-JOBS | Jobs | select, create, archive | empty, populated | desktop, narrow | TBD |
| mapping_missing | CAP-MAP | Mapping | selectboxes | warning unresolved | desktop | TBD |
| rules_run_selected | CAP-RULES | Rules | multiselect, run, sliders | progress, results, fail | desktop | TBD |
| plots_fault_overlay | CAP-PLOTS | Plots | equipment, rule, chart | empty, overlay | desktop | TBD |
| findings_disposition | CAP-FINDINGS | Findings | status, notes, save | conflict revision | desktop | TBD |
| wattlab_handoff | CAP-WATTLAB | WattLab | export/handoff | success | desktop | TBD |

## Capture protocol (when display available)

```bash
# Documented placeholder — implement in CI with Playwright against Streamlit.
# Mask timestamps, tokens, and absolute paths before storing under
# docs/migration/react-rust/evidence/screenshots/<commit>/
```

Record commit SHA + fixture hash in `PARITY_EVIDENCE.md`.
