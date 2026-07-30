---
title: OFDD 065-076 parity (Gate A-C)
parent: Migration
nav_order: 40
---

# OFDD 065–076 parity register

**Date:** 2026-07-30 · Branches `fix/ofdd-gate-a-sites-sql-413` (Gate A) →
`fix/ofdd-gate-b-c-findings-ecm` (Gate B + Gate C, built on the Gate A tip).
**Updated:** Liberty soak `parity_hunt_20260730T003200Z` residuals filled below.

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
| OFDD-073 | Multi-site Streamlit UI + Hive purge | A | **VERIFIED (bench) / PENDING Liberty soak** | Session sites + Delete site UI verified earlier. Tip also purges `.cache/rule_results/building={id}/` on `DELETE /api/datasets` (OFDD-073 residual from 2026-07-29 soak). Liberty re-soak still required to prove B50 gone / B100 intact. |
| OFDD-066 | Skip-not-crash on missing roles | A | **VERIFIED** | Runner preflights `required_roles` vs history schema and classifies DataFusion schema errors → `SKIPPED_MISSING_ROLES` (`rules_skipped`), not `rules_failed`. `results_response` emits per-row status (`SKIPPED_MISSING_ROLES`/`FAULT`/`PASS`). |
| OFDD-068 | Weather table/view | A | **VERIFIED** | `register_weather_if_present` falls back to a `weather` SQL view over `history` weather-station rows (`equipment_id ILIKE '%weather%'/'%meteo%'/'%oat%'`) when no `weather/` sidecar. Unit test covers the fallback. |
| OFDD-075 | Analytics 413 | A | **VERIFIED** | `DefaultBodyLimit::max(128 MiB)` on the protected router (analytics + `fdd/run`); CSV nest already had its own limit. |
| OFDD-065 | Directional FAULT parity (SV-STALE / VAV-1 / FC1) | A | **DIRECTIONAL / residual** | Liberty 2026-07-30 deltas filled (SV-STALE/VAV-1 still **WIDE**; FC1/OAT-METEO **TIGHT**). Do not close with bench-only. |
| OFDD-070 | Economizer historian | B | **FIXED tip (OFDD-070b CTE)** | Damper projected into CTE; Liberty re-soak required to clear stub residual. |
| OFDD-076 | Jobs site bind | C | **FIXED tip (OFDD-076b)** | `CreateJobBody.building_id` → `site_id` when empty. |

## Known FAULT deltas (Liberty B50/B100 — soak 2026-07-30)

From Liberty soak `parity_hunt_20260730T003200Z` vs tip `sha-064eadb` (vibe19
`fdd_summary.csv`). Do **not** flip `proven` from these alone — WIDE bands need
smoking-gun SQL + cheap fixtures first.

| Rule | Building | vibe19 FAULT hrs | open-fdd FAULT hrs | Δ | Band | Root-cause hypothesis |
|------|----------|------------------:|-------------------:|--:|------|-----------------------|
| SV-STALE | B50 | 884 | 3384 | +2500 | **WIDE** | stale-window / fan-on confirm vs pandas |
| SV-STALE | B100 | 543 | 3271 | +2728 | **WIDE** | as above |
| VAV-1 | B50 | 2815 | 24550 | +21735 | **WIDE** | comfort-band confirm vs pandas `confirm_fault()` |
| VAV-1 | B100 | 3789 | 21615 | +17826 | **WIDE** | as above |
| FC1 | B100 | 205 | 220 | +15 | **TIGHT** | duct-static ε / fan-on fraction |
| OAT-METEO | both | match | match | 0 | **TIGHT** | — |
| ECON-1 | B50 | 700 | 0.6 | −699 | **WIDE** | inverted / role mapping |
| ECON-2 | B50 | 191 | 3143 | +2952 | **WIDE** | screening vs pandas |
| FAULT-ELAPSED-HOURS | B50 | 0 | 11325 | +11325 | **WIDE** | SQL-only status rollup honesty |
| SCHED-247 | B50 | 0 | 3235 | +3235 | **WIDE** | streak ≠ window `always_on_pct` |

## OFDD-065 residual (honest)

Liberty deltas are filled (above). **SV-STALE** / **VAV-1** remain **WIDE**;
**FC1** / **OAT-METEO** are **TIGHT**. This pass does **not** flip registry
`proven` without smoking-gun SQL + cheap fixtures. Priority tighten targets:
VAV-1 confirm/band, ECON-1/2 inverted, FAULT-ELAPSED-HOURS honesty, SCHED-247
residual note. Re-soak after OFDD-070b CTE for economizer Overview.

## Gate B — vibe19 tip UI / Findings / economizer (branch `fix/ofdd-gate-b-c-findings-ecm`)

| Ticket | Scope | Gate | Status | Notes |
|--------|-------|------|--------|-------|
| OFDD-074 / 069 | Eng Findings HITL; retire Generic RCx DOCX story | B | **VERIFIED (bench) / PENDING Liberty soak** | UI Eng Findings panel verified earlier. Tip adds `GET /api/reports/engineering-findings` (most recent `engineering_findings` draft, else 404). Liberty soak still required to prove artifacts after FDD run. |
| OFDD-070 | Economizer historian/building-scoped Overview | B | **VERIFIED (bench) / PENDING Liberty soak** | Building scope verified earlier. Tip accepts Liberty `web_oa_t` (and rat/mat aliases) in `economizer_from_history` so scoped history no longer falls through to the stub warning when the econ trio is present under web_* names. Liberty re-soak still required. |
| OFDD-071 | OpenAPI live routes + health version = tip SHA | B | **VERIFIED (bench) / PENDING image soak** | `resolve_build_version()` logic verified. Tip bakes `OPENFDD_GIT_SHA` into central Dockerfile + GHCR build-arg so `/api/health` reports `{version}+{sha}` on published images (was bare `3.3.0` on `sha-766dbc1`). |

## Gate C — vibe20 in-product Jobs / ECM (branch `fix/ofdd-gate-b-c-findings-ecm`)

| Ticket | Scope | Gate | Status | Notes |
|--------|-------|------|--------|-------|
| OFDD-076 / 072 | In-product vibe20 Jobs agent-build + cascade-if-ready | C | **VERIFIED (delegated) / PENDING Liberty soak** | Jobs ECM request path remains delegated (Excel still vibe20). Tip persists `building_id` → `site_id` / `building_name` on `POST /api/jobs` create-from-site (OFDD-076 residual). Gate C exit still requires operator ECM without a separate vibe20 container. **ENH-OFDD-007:** UI honestly links real `.xlsx` to vibe20 `wattlab notebook agent-build` / `reports/notebooks/**` — do not market Gate C as vibe20-complete for spreadsheets. |

## Gate B/C honesty caveats

- **2026-07-29 Liberty soak** downgraded several Gate B/C **VERIFIED** claims
  (economizer stub on `web_oa_t`, Eng Findings API 404, delete-site ghost
  rule_results, Jobs `site_id` null, health bare `3.3.0`). This tip lands the
  code-path fixes; Liberty zip re-soak still owns filling the FAULT deltas table
  and confirming UX parity.
- **No Liberty zips in CI**, so Eng Findings / economizer / SV-STALE / VAV-1
  gates are proven on synthetic fixtures + unit/integration tests, not a
  B50/B100 soak.
- ECM agent-build and any EnergyPlus calibration are **delegated** (WattLab /
  external runner). open-fdd is not marketed as vibe20-complete: the in-product
  path records requests and queues external runs; it does not itself parse IDF or
  run EnergyPlus.
