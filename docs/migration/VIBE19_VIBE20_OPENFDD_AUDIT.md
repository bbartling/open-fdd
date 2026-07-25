---
title: Vibe19 / Vibe20 / Open-FDD audit
parent: Migration
nav_order: 1
---

# Vibe19 × Vibe20 × Open-FDD audit

**Audit date:** 2026-07-25 · **Tip under audit:** `d631e9c8` (`sha-d631e9c`, merge #569)  
**Rule:** trust tested current code over historical `docs/migration/vibe19/*` stage notes.

Reference checkouts (not vendored into open-fdd):

| Tree | Path |
|------|------|
| vibe19 | `/mnt/c/Users/ben/Documents/py-bacnet-stacks-playground/vibe_code_apps_19` (`develop`) |
| vibe20 | `/mnt/c/Users/ben/Documents/py-bacnet-stacks-playground/vibe_code_apps_20` (`develop`) |
| open-fdd UI (vendored vibe19 lab) | [`services/ui/`](../../services/ui/) |

Companion matrices:

- [vibe19 capability parity](vibe19_parity_matrix.md)
- [vibe20 / WattLab integration](vibe20_integration_matrix.md)
- Rule SQL↔pandas honesty: [docs/rules/cookbook/parity-matrix.md](../rules/cookbook/parity-matrix.md)

---

## A. Open-FDD current state

### Stack

| Image | Role (code truth) |
|-------|-------------------|
| `openfdd-central` | JWT REST, Feather ingest, DataFusion FDD (`POST /api/fdd/run` registry mode) |
| `openfdd-ui` | **Streamlit** vibe19 lab (`services/ui`) — not React |
| `openfdd-fieldbus` | BACnet / Modbus / Haystack / REST OT |
| `openfdd-mqtt` | MQTTS broker |
| `openfdd-mcp` | Optional MCP stdio → central |

Retired: `openfdd-edge-rust` monolith (see closed #570).

### FDD execution path

```text
Package / CSV / OT → Feather + parquet (.cache/parquet)
        → POST /api/fdd/run { mode: registry }
        → edge registry_api + crates/fdd_rules
        → sql_rules/*.sql via DataFusion (fdd_sql)
        → .cache/rule_results/<RULE_ID>.json
```

- Canonical registry: [`sql_rules/registry.yaml`](../../sql_rules/registry.yaml) — **63** rules / **63** SQL files.
- Pandas cookbook: [`services/ui/app/rules/cookbook_catalog.py`](../../services/ui/app/rules/cookbook_catalog.py) — **59** rules; emergency only via `OPENFDD_ALLOW_PANDAS_FDD=1`.
- Parity tags (2026-07-19 matrix): **18** `proven_building_100`, **44** `ported_from_cookbook`, **1** `skipped_missing_roles` (`FC7`).

### Durable site state (not analysis Jobs)

Under bind-mounted [`workspace/`](../quick-start/site-lifecycle.md):

| Path | Purpose |
|------|---------|
| `workspace/data/session_config.json` | FDD session / fault settings (`/api/fdd/session-config`) |
| `workspace/data/datasets/` | Dataset registry |
| `workspace/data/csv_buildings/` | Package materializations |
| `workspace/data/feather_store/` | Historian |
| `workspace/data/import_jobs/` | CSV **import** tickets (`import-{millis}`) — not FDD analysis Jobs |

Streamlit continuity today: `st.session_state` + browser download/upload of `session_config.json` ([`streamlit_app.py`](../../services/ui/streamlit_app.py)).

### UI sections (frozen contract)

[`dashboard_contract.py`](../../services/ui/app/dashboard_contract.py): Overview · Data Model · Run Rules · Results by Category · FDD Plots · RCx Plots · Metering · Export.  
**No Jobs page.** Single large `streamlit_app.py` (not multipage).

### WattLab / EnergyPlus

- Export handoff implemented: [`wattlab_dump.py`](../../services/ui/app/wattlab_dump.py) (`wattlab_dump_v3`).
- EnergyPlus / ECM / calibration live in **external** vibe20 (`wattlab/`), not in this repo.

---

## B. Vibe19 features missing or partial in Open-FDD

| Capability | Vibe19 | Open-FDD gap |
|------------|--------|--------------|
| Persistent named Jobs | Session-oriented demo | **Missing** product Job save/open/reopen |
| Multipage IA | Similar section radio | Same 8 sections; no Jobs / Findings / History pages |
| FDD rule math | Pandas cookbook | **SQL default** (good); catalog skew 59 vs 63 |
| RCx analytics | `rcx_plots.py` + analytics | Vendored pandas path; not DataFusion-first |
| Engineering findings as first-class entities | reporting / HITL in playground | Export CSVs only; no persisted dispositions |
| Filled RCx DOCX | playground reporting pipeline | Template download only (`docx_report.py`) |
| Dual BAS vs web OAT honesty | Present | Present in UI/weather helpers — keep |
| Mech cooling proof hierarchy | Specs under `services/ui/docs/superpowers/` | Logic in pandas analytics; needs DF migration later |

See [vibe19_parity_matrix.md](vibe19_parity_matrix.md) for Intake → Findings rows.

---

## C. Vibe20 features worth integrating (handoff, not rewrite)

Integrate **into the Job model** as consumers of Open-FDD evidence:

| Area | vibe20 path | Open-FDD action |
|------|-------------|-----------------|
| Seed / dump import | `wattlab/seed/bundle.py` | Persist handoff under `job/wattlab/`; avoid full pandas recompute |
| Assumptions / gaps | studio / seed honesty | Persist `NEEDS_INPUT` gaps with job |
| EnergyPlus runs | `wattlab/energyplus/` | Out of process; store run metadata + hashes only |
| ECM / finance | `wattlab/ecm/`, `finance.py` | Out of process |
| Bills | `wattlab/seed/import_bills.py` | Optional job artifact |

Do **not** vendor EnergyPlus into open-fdd.

---

## D. Pandas inventory (significant `services/ui` uses)

| Module | Class | Notes |
|--------|-------|-------|
| `app/rules/cookbook_catalog.py`, `runner.py`, `pid_hunting.py`, `sensor_rate.py`, `operational_gate.py`, `economizer_weather.py` | **TEST_ORACLE** (+ emergency FDD) | Keep until SQL proven; never silent prod fallback |
| `app/analytics.py`, `analytics_baseline.py` | **MIGRATE_TO_DATAFUSION** | Motor runtime, mech cooling, sensor health |
| `app/rcx_plots.py`, `ui_rcx_tab.py` | **MIGRATE_TO_DATAFUSION** | Plot datasets must be DF-prepared |
| `app/metering.py` | **MIGRATE_TO_DATAFUSION** | Meter aggregations |
| `app/wattlab_dump.py`, `model_seed.py` | **MIGRATE_TO_DATAFUSION** (prep) + **KEEP_NON_SQL** (zip/IO) | Stats/profiles → SQL; zip assembly stays Python |
| `app/charts.py`, `streamlit_app.py`, `reports.py` | **UI_BOUNDARY** | After aggregation only |
| `app/data_loader.py`, `package_io.py`, `sql_sources.py`, weather helpers | **KEEP_NON_SQL** / thin frames | I/O and package validation |
| `app/agent_api.py` | Mixed | Prefer central SQL for FDD; analytics still pandas |

---

## E. Duplicate algorithms

| Concern | Locations | Resolution |
|---------|-----------|------------|
| Rule catalog | `sql_rules/registry.yaml` vs cookbook 59 | SQL is production SoT; cookbook = oracle |
| FC13 naming | SQL `FC13-SAT-HIGH` + alias `FC13` | Keep alias; document |
| Session config | central `session_config` vs Streamlit download | Unify under Job config revision |
| WattLab findings | `wattlab_dump.fdd_findings_table` vs Results UI | One findings schema under Job |
| RCx presets | UI `REQUIRED_RCX_PRESET_IDS` vs playground | Keep open-fdd contract; port behavior not bugs |

---

## F. Job persistence state

| Exists | Missing |
|--------|---------|
| Site `workspace/` durability | Named analysis `job_id` |
| CSV import job tickets | Create / open / save / duplicate / archive Jobs UX |
| session_config round-trip | Revision/provenance stamps on FDD/RCx/findings |
| Rule result JSON cache | Stale detection vs mapping/config change |
| WattLab zip in session | Job-attached wattlab/ run history |

**Target layout (PR1+):**

```text
workspace/jobs/<job_id>/
  job.json                 # metadata + revision hashes
  mapping/
  configs/
  runs/
  findings/
  reports/
  wattlab/
  artifacts/
  # telemetry: pointers / links into feather_store + parquet — never SQLite blobs
```

SQLite (if introduced later) = **job metadata index only**.

---

## G. Proposed target architecture

```text
                ┌─────────────────────┐
                │   STREAMLIT UI      │
                │ Jobs + engineering  │
                └──────────┬──────────┘
                           │ thin typed calls
         ┌─────────────────▼─────────────────┐
         │   OPEN-FDD SERVICES (central)     │
         │ jobs / mapping / runs / findings  │
         └───────────────┬───────────────────┘
                         │
          ┌──────────────▼──────────────┐
          │ RUST + ARROW + DATAFUSION   │
          │ FDD / RCx / analytics SQL   │
          └──────────────┬──────────────┘
                         │
              Feather / parquet under workspace
                         │
                         ▼ engineering evidence
             ┌────────────────────────┐
             │ WATTLAB / ENERGYPLUS   │  (external vibe20)
             └────────────────────────┘
```

Contracts: [datafusion-first](../architecture/datafusion-first.md) · [job-workspaces](../architecture/job-workspaces.md) · [analytics-boundary](../architecture/analytics-boundary.md).

---

## H. Migration stages (backlog)

| Stage | Scope | Status |
|-------|--------|--------|
| **PR0** | This audit + matrices + tip pin + architecture stubs | This PR |
| **PR1** | Job filesystem contract + tests + thin Jobs UI entry | Next |
| **PR2** | DataFusion analytics service boundary + instrumentation | Planned |
| **PR3** | FDD oracle push (`ported` → `proven`) | Planned |
| **PR4** | RCx family → SQL views | Planned |
| **PR5** | Full Jobs UX restore (mapping/params/runs) | Planned |
| **PR6** | FDD/RCx UI parity (registry-driven sliders; DF plots) | Planned |
| **PR7** | Findings + job reports | Planned |
| **PR8** | WattLab bridge v2 (job-native handoff) | Planned |
| **PR9** | Energy model metadata under job (external EP) | Planned |
| **PR10** | Perf benches + delete production pandas paths after parity | Planned |

### Non-goals

- Wholesale copy of vibe19/vibe20 trees  
- React UI rewrite  
- Historian in SQLite  
- Silent pandas FDD fallback  
- Claiming full SQL↔pandas parity  

### Next recommended code PR

**PR1 — Job contract** under `workspace/jobs/<job_id>/` with create / list / get / archive, atomic `job.json` writes, reopen restores metadata + mapping pointers, thin Streamlit Jobs entry. Defer multipage IA rewrite to PR5.
