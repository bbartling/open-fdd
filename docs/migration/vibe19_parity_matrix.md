---
title: Vibe19 capability parity matrix
parent: Migration
nav_order: 2
---

# Vibe19 → Open-FDD capability parity matrix

**Audit tip:** `sha-8850b0b` · **Rule SQL honesty:** [parity-matrix.md](../rules/cookbook/parity-matrix.md) (do not duplicate rule-level tables here).

**Product UI:** one Streamlit app (`services/ui`) — vibe19 workflows + WattLab export. Pandas cookbook stays online + vibe19-tested; Open-FDD RS FDD is DataFusion SQL only.

Status legend: **DONE** · **PARTIAL** · **MISSING** · **N/A** (intentional).

| Capability | Vibe19 path | Open-FDD equivalent | Backend | DataFusion? | UI parity? | Tests? | Status | Notes |
|------------|-------------|---------------------|---------|-------------|------------|--------|--------|-------|
| Folder import | `data_loader` / folder picker | Streamlit folder when `allow_server_paths` | UI + package_io | N/A | Yes | Partial | PARTIAL | Zip always on; folder gated |
| ZIP / package import | `package_io` | `package_io` + central Feather | UI + edge csv package | Ingest→parquet | Yes | Yes | DONE | Hostile ZIP handling in package path |
| Multi-file workflows | package | package + datasets API | edge datasets | Via parquet | Yes | Yes | DONE | |
| Package validation | package_io | package_io + report | UI | N/A | Yes | Yes | DONE | |
| Session configuration | session_config | `/api/fdd/session-config` + download/upload | edge session_config | N/A | PARTIAL | Yes | PARTIAL | Not job-scoped yet |
| Equipment inventory | data model tree | `data_model_tree` | UI | N/A | Yes | Guards | DONE | |
| Role mapping | mapping wizard / role_map | Data Model section | UI + central roles | N/A | Yes | Partial | PARTIAL | No mapping revision stamp |
| VAV→AHU relationships | data model | tree / attrs | UI | N/A | PARTIAL | Partial | PARTIAL | |
| Overview summary | Overview tab | Overview section | UI | N/A | Yes | Guards | DONE | |
| Occupancy calendar | occupancy schedule | session + Overview | UI | **Need SQL view** | PARTIAL | Partial | PARTIAL | Not a DF relation yet |
| BAS vs web OAT | weather helpers | weather_resolver / open_meteo / charts | UI | Migrate | Yes | Partial | PARTIAL | Provenance must stay explicit |
| FDD run all / selected | rules runner | `POST /api/fdd/run` registry | fdd_rules | **Yes** | Yes | Yes | DONE | Default SQL; pandas quarantine |
| Rule param tuning | sliders / cookbook | left-rail + aliases | UI + registry_api | Params→SQL | PARTIAL | Soak #565 | PARTIAL | Dual catalog 59 vs 63 |
| Fault statuses | cookbook statuses | SQL result statuses | fdd_rules | Yes | Yes | Fixtures | PARTIAL | Ported ≠ proven for 44 rules |
| Confirmation windows | confirm_fault | CONFIRM_ROWS / confirm_min | runner | Yes | Yes | #565 | DONE | |
| FDD Plots | charts | FDD Plots section | UI charts | UI boundary | Yes | Guards | PARTIAL | Still frame-fed |
| RCx presets (~20) | rcx_plots | RCx Plots + REQUIRED_RCX_PRESET_IDS | pandas | **No** | Yes | Coverage helper | PARTIAL | Migrate datasets to DF |
| Motor / weekly runtime | analytics | analytics.py | pandas | **No** | Yes | Partial | PARTIAL | MIGRATE |
| Mech cooling evidence | analytics / specs | analytics + superpowers specs | pandas | **No** | PARTIAL | Specs | PARTIAL | Keep hierarchy; move math to DF |
| Metering | metering | Metering section | pandas | **No** | Yes | Partial | PARTIAL | MIGRATE |
| Engineering findings HITL | reporting/ | Export CSVs / wattlab findings | export | N/A | **No** page | Partial | MISSING | Need persisted findings |
| Filled RCx DOCX | reporting pipeline | Template download only | docx_report | N/A | Partial | Guards | MISSING | No python-docx fill |
| WattLab dump | wattlab_dump | Export “WattLab dump” | wattlab_dump | Mixed | Yes | Fixtures | DONE | Recompute cost still high |
| Named Jobs persistence | (demo session) | `workspace/jobs/` + sidebar | job_store | N/A | Thin | Yes | PARTIAL | PR1 landed; full restore UX later |
| Agent / REST tools | agent_api | central `/api/agent/tools` + MCP | central | FDD SQL | N/A | Smoke | DONE | Extend with job tools later |

## Registry honesty (pointer)

Do not claim “54 full parity.” Use `parity_status` on each rule in `sql_rules/registry.yaml`. UI cookbook count **59** vs SQL **63** is intentional (SQL rollups + FC13 alias).
