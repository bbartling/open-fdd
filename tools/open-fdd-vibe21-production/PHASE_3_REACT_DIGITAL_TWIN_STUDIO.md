# Phase 3 — React Digital Twin Studio

## Objective

Turn the thin WattLab handoff page into a guided, job-centered engineering
workflow that integrates Open-FDD analytics/FDD with twin creation,
calibration evidence, scenario testing, and deliverables. React remains the
exact engineering surface; Unity is added in Phase 4 as a spatial viewer.

## Navigation model

Within a selected job, provide these primary steps:

1. **Inputs** — site/building, utility/BAS files, weather, IDF, schedules,
   geometry, and provenance.
2. **Data & FDD** — mapping, quality, analytics, FDD findings, dispositions.
3. **Twin** — twin versions, calibration evidence, assumptions, readiness.
4. **Scenarios** — demand response first; later approved ECM families.
5. **3D Viewer** — Unity availability/build/version and spatial selection.
6. **Deliverables** — reports, workbooks, model cards, exports, audit manifest.

The studio may display completion/readiness, but it must allow safe revisiting
and must not convert engineering review into a dishonest linear wizard.

## P3-M0 — Information architecture and state contract

### PRs

- Define URL/deep-link schema for job, step, twin version, run, equipment,
  scenario, time cursor, and visual mode.
- Define which state is local, URL-shareable, cached query data, draft backend
  state, or immutable artifact state.
- Add unsaved-change, stale revision, multi-tab conflict, and restore behavior.
- Produce canonical desktop layouts and responsive rules using the existing
  Open-FDD design tokens.

### Gate

- Refresh/back/forward/deep-link preserve expected context.
- Two browser tabs cannot silently overwrite the same draft.
- A route can be shared without leaking secrets or local paths.

## P3-M1 — Inputs and readiness

### PRs

- Structured upload controls for utility, BAS, IDF, EPW/weather, geometry, and
  manifests with progress/cancel/resume where needed.
- Preflight: hashes, MIME/content checks, schema/version, timezone, unit,
  timestamp coverage, duplicate rows, missing roles, and licensing attestation.
- Site/building/equipment binding review using stable Open-FDD IDs.
- Readiness cards driven from backend evidence, not hard-coded frontend logic.

### Gate

- Invalid archives/paths/content fail safely.
- Users can trace every accepted input to a hash and provenance source.
- The studio clearly distinguishes missing, optional, and blocking inputs.

## P3-M2 — Analytics/FDD-to-twin evidence bridge

### PRs

- Select FDD/analytics runs as calibration or modeling evidence.
- Show data quality, coverage, faults, and unresolved dispositions alongside
  twin assumptions.
- Add immutable evidence links from twin versions and scenarios back to source
  datasets, mappings, rules, and findings.
- Prevent activation when configured blockers are unresolved; allow explicit
  engineering waivers with reason, role, and expiry.

### Gate

- A reviewer can navigate result → rule/parameters → mapped points → source
  observations → twin assumption without losing job context.

## P3-M3 — Twin version and calibration workspace

### PRs

- Twin version list, compare, fork, approve, supersede, and archive.
- Calibration views for monthly and, when available, hourly evidence.
- ASHRAE G14 or configured metric cards with sample count, period, exclusions,
  and pass/fail thresholds; never display a pass without its calculation record.
- Assumption/register editor for geometry, schedules, systems, weather,
  calibration adjustments, limitations, and reviewer notes.
- External EnergyPlus run status, logs, artifacts, retries, and digest-pinned
  worker provenance.

### Gate

- Every calibration metric is server-computed, reproducible, and linked to its
  inputs.
- Users can compare versions without mutating approved evidence.

## P3-M4 — Scenario laboratory

### PRs

- Schema-driven strategy forms and presets.
- Baseline and multi-scenario comparisons with exact tables and Plotly charts.
- Time-series demand, end-use, AHU/plant/zone targets, comfort warnings, peak
  windows, rebound, cumulative energy, and domain status.
- Parameter sensitivity/batch runs within bounded quotas.
- Save draft, run, clone, compare, approve for demo/use, and export.
- Explicit labels for `MEASURED`, `ENERGYPLUS_SIMULATED`, `ML_SURROGATE`,
  `REPLAY`, and `DEMO` at chart, table, download, and report levels.

### Gate

- Numerical results match Phase 2 API fixtures.
- Rapid slider changes cancel stale requests and never flash an old result as
  current.
- Out-of-domain and unavailable states are impossible to miss.

## P3-M5 — Deliverables and workflow completion

### PRs

- Engineering HTML/PDF/CSV/JSON exports from authoritative run artifacts.
- Offline PyPI workbook handoff with schema/version/hash and import-back
  validation; spreadsheets are tools/evidence, not production computation.
- Twin package export excluding secrets and private absolute paths.
- Reviewer signoff, waiver summary, model/twin status, and reproducibility
  manifest.

## Phase 3 exit gates

- All six studio sections pass real-stack Playwright tests.
- Representative workflow runs from raw inputs through a scenario deliverable.
- No structured workflow relies on raw JSON textareas.
- Every number and status has an API owner and provenance link.
- Accessibility, visual, failure, concurrency, and large-upload tests pass.
- Unity may still be unavailable; its section clearly reports that state without
  breaking the engineering workflow.

