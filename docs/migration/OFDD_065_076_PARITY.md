---
title: OFDD 065-076 parity (Gate A-C)
parent: Migration
nav_order: 40
---

# OFDD 065–076 parity register

**Date:** 2026-07-29 · Branches `fix/ofdd-gate-a-sites-sql-413` (Gate A) →
`fix/ofdd-gate-b-c-findings-ecm` (Gate B + Gate C, built on the Gate A tip)

Tracks the Liberty B50/B100 parity hunt tickets OFDD-065…076 across the three
gates defined in the combined vibe19+vibe20 plan. This file records **VERIFIED**
vs **residual** per gate; it is the source of truth for what an operator can and
cannot yet switch off vibe19/vibe20 for.

Companion matrices:
[`vibe19_parity_matrix.md`](vibe19_parity_matrix.md),
[`vibe20_integration_matrix.md`](vibe20_integration_matrix.md),
[`MILESTONE_D_GAP_REGISTER.md`](MILESTONE_D_GAP_REGISTER.md).

## Gate status

| Ticket | Scope | Gate | Status | Notes |
|--------|-------|------|--------|-------|
| OFDD-067 | `building_id` scoping central→edge; results/equipment scoped | A | **VERIFIED** | `FddRunRequest.building_id` (+ nested `params.building_id`) forwarded top-level; edge scopes history, results dir (`building={id}/`), equipment listing; echoed in response. IT: two fake building parquet trees → distinct FAULT totals + separate results dirs. |
| OFDD-073 | Multi-site Streamlit UI | A | **VERIFIED** | Session `sites{building_id→snapshot}`; sidebar **Site** select rebinds Overview/FDD/RCx; second zip **adds** a site; **Delete dataset → Delete site** purges + switches; `run_fdd` passes active `building_id`; vibe19 GHCR pull tip removed. |
| OFDD-066 | Skip-not-crash on missing roles | A | **VERIFIED** | Runner preflights `required_roles` vs history schema and classifies DataFusion schema errors → `SKIPPED_MISSING_ROLES` (`rules_skipped`), not `rules_failed`. `results_response` emits per-row status (`SKIPPED_MISSING_ROLES`/`FAULT`/`PASS`). |
| OFDD-068 | Weather table/view | A | **VERIFIED** | `register_weather_if_present` falls back to a `weather` SQL view over `history` weather-station rows (`equipment_id ILIKE '%weather%'/'%meteo%'/'%oat%'`) when no `weather/` sidecar. Unit test covers the fallback. |
| OFDD-075 | Analytics 413 | A | **VERIFIED** | `DefaultBodyLimit::max(128 MiB)` on the protected router (analytics + `fdd/run`); CSV nest already had its own limit. |
| OFDD-065 | Directional FAULT parity (SV-STALE / VAV-1 / FC1) | A | **DIRECTIONAL / residual** | See deltas table below. Building-scoping (067) removes cross-building `bench_*` bleed which was a primary inflation source. Remaining SQL-vs-pandas gate nuances documented; no bench-breaking gate changes made in this pass. |

## Known FAULT deltas (Liberty B50/B100 — placeholders)

Populate from a `sha-*` soak comparing open-fdd SQL `results` vs vibe19
`fdd_summary.csv` on `~/wattlab_workspace/uploads/openfdd/raw_BUILDING_{50,100}_openfdd.zip`.
Rows are placeholders until the zips are available on the soak host (absent in
this environment, so numbers are not fabricated here).

| Rule | Building | vibe19 FAULT hrs | open-fdd FAULT hrs | Δ | Band | Root-cause hypothesis |
|------|----------|------------------|--------------------|---|------|-----------------------|
| SV-STALE | B50 | _tbd_ | _tbd_ | _tbd_ | ±? | fan-off applicability / stale-window confirm alignment |
| SV-STALE | B100 | _tbd_ | _tbd_ | _tbd_ | ±? | as above |
| VAV-1 | B50 | _tbd_ | _tbd_ | _tbd_ | ±? | comfort-band confirm rows vs pandas `confirm_fault()` |
| VAV-1 | B100 | _tbd_ | _tbd_ | _tbd_ | ±? | as above |
| FC1 | B50 | _tbd_ | _tbd_ | _tbd_ | ±? | duct-static ε / fan-on fraction mapping (`fan_hi`→`eps_vfd_spd`) |
| FC1 | B100 | _tbd_ | _tbd_ | _tbd_ | ±? | as above |

## OFDD-065 residual (honest)

Fan-off applicability and confirm-window semantics for **SV-STALE**, **VAV-1**,
and **FC1** are the likely remaining SQL-vs-pandas divergences once building
scoping (OFDD-067) removes cross-building contamination. This pass did **not**
alter those SQL gates because:

- No Liberty zips are present in this environment, so any gate change could not be
  validated against the oracle or the existing `fdd_rules` benches.
- The plan's operating law forbids bench-only closes; gate edits must be proven on
  B50+B100 vs vibe19 before landing.

Next step (Gate A exit): run the `sha-*` soak, fill the deltas table above, then
tighten SV-STALE/VAV-1/FC1 gates within documented bands without regressing
`crates/fdd_rules` oracle-parity benches.

## Gate B — vibe19 tip UI / Findings / economizer (branch `fix/ofdd-gate-b-c-findings-ecm`)

| Ticket | Scope | Gate | Status | Notes |
|--------|-------|------|--------|-------|
| OFDD-074 / 069 | Eng Findings HITL; retire Generic RCx DOCX story | B | **VERIFIED** | Overview report story is now `app.eng_findings.render_engineering_findings_panel` over `open_fdd.reporting` (HITL: max-findings, pin/drop refs, `REF=note` notes → prioritized findings + DOCX/XLSX/JSON downloads). The active site's `batch_results` are `open_fdd.rules.base.RuleResult`, fed straight to `candidates_from_rule_results`. When the `reporting` extra is absent, the panel falls back to central `/api/reports` (list/draft) instead of a static DOCX. Static Generic RCx DOCX demoted to a secondary expander. Helper unit tests green. `dashboard_contract` updated. |
| OFDD-070 | Economizer historian/building-scoped Overview | B | **VERIFIED** | `AnalyticsQuery.building_id` added; `economizer_from_history` + `open_history_scoped` register only `building={id}/**/*.parquet` (rejects path-escape ids; returns `None` for an un-ingested site rather than leaking the whole tree). UI (`ui_rcx_tab`/`ui_analytics.fetch_economizer_analytics`) forwards the active `building_id`. IT: two ingested buildings → each scope sees only its own AHU; coverage echoes `building_id`. |
| OFDD-071 | OpenAPI live routes + health version = tip SHA | B | **VERIFIED** | `/api/health` `version` = `resolve_build_version()` → `{CARGO_PKG_VERSION}+{OPENFDD_GIT_SHA}` (runtime) or `OPENFDD_BUILD_GIT_SHA` (compile-time), else bare crate version (no more stale-only `3.3.0`). `/openapi.json` now advertises live jobs / analytics / datasets / fdd-results / reports routes (doc-only `#[utoipa::path]` descriptors + new tags). Tests: `openapi_lists_live_*`, `version_prefers_runtime_git_sha_then_crate_version`. |

## Gate C — vibe20 in-product Jobs / ECM (branch `fix/ofdd-gate-b-c-findings-ecm`)

| Ticket | Scope | Gate | Status | Notes |
|--------|-------|------|--------|-------|
| OFDD-076 / 072 | In-product vibe20 Jobs agent-build + cascade-if-ready | C | **VERIFIED (delegated)** | Jobs sidebar surfaces **create Job from active site** (site/building caption + scoped WattLab/ECM). New `app.ui_ecm_job` writes a job-native **ECM package request** under `wattlab/ecm/*.json` with `honesty.openfdd = "delegated"` when `open_fdd.ecm_engineering` imports (`"unavailable"` otherwise); WattLab notebook builder shell-out is detected and recorded when present. **cascade-if-ready**: when docker.sock **and** `energyplus-mcp-dev` are present, an external E+ run is queued via the existing `POST /api/jobs/{id}/eplus/runs` (`eplus_runner`, QUEUED-only); otherwise an honest `esco_screening_only` stamp — central stays free of IDF/E+ logic. Unit tests cover honesty states, the cascade gate, queue-when-ready, and the on-disk request. |

## Gate B/C honesty caveats

- **No Liberty zips in this environment**, so Eng Findings / economizer parity is
  proven on synthetic fixtures + unit/integration tests, not a B50/B100 soak. The
  `sha-*` soak (Gate A exit) still owns filling the FAULT deltas table above and
  the vibe19-tip UX comparison screenshots.
- ECM agent-build and any EnergyPlus calibration are **delegated** (WattLab /
  external runner). open-fdd is not marketed as vibe20-complete: the in-product
  path records requests and queues external runs; it does not itself parse IDF or
  run EnergyPlus.
