---
name: Hybrid diagnostics AHU VAV program
overview: "Experimental Wave G after soft-OPEN closeout. Semantic hybrid ML/Physics first vertical slice for AHU+VAV only — real train/score, Overview column, EnergyPlus calibration export. Not mature/production-qualified without measured gates. Incremental 3.3.37→3.3.42."
todos:
  - id: g0-inventory
    content: "G0 — Reconcile tip vs proposal (40ac066 era); inventory actual vs promised; short plan; update stale guidance; no product code yet"
    status: pending
  - id: g37-semantic
    content: "3.3.37 — Detector/feature manifests + applicability (AHU/VAV supported; other families explicit N/A reasons)"
    status: pending
  - id: g38-features
    content: "3.3.38 — Shared DataFusion/Arrow feature pipeline; typed dataset; no zero-fill missing physics"
    status: pending
  - id: g39-ml
    content: "3.3.39 — Seeded KMeans regimes + within-regime deviation; background jobs; persisted artifacts"
    status: pending
  - id: g40-physics
    content: "3.3.40 — AHU mixing + VAV sensible residuals with honest observability gates"
    status: pending
  - id: g41-overview
    content: "3.3.41 — Overview ML/Physics column + evidence drilldown; no train-on-page-load; no Plotly on Overview"
    status: pending
  - id: g42-export
    content: "3.3.42 — EnergyPlus calibration export purpose (primary) + research reproducibility bundle; completeness tests"
    status: pending
  - id: g-gates
    content: "G-gates — Synthetic-59 + required unit/contract tests; optional labeled AHU/VAV set or document blocker + disable research claims"
    status: pending
isProject: false
---

# Wave G — Semantic hybrid diagnostics (AHU + VAV first slice)

**Parent:** [`openfdd_post_3.3.33_soft_open_program.plan.md`](openfdd_post_3.3.33_soft_open_program.plan.md) (Cursor: `post_3.3.33_soft_open_master_a1b2c3d4.plan.md`)

**Status:** experimental extension of an actively changing AFDD platform. Useful mechanical diagnostics with reproducible artifacts — **not** scientifically validated / production-qualified without evidence.

**Start only after** soft-OPEN D→E→F + **full Railway closeout** PASS (or explicit operator waiver). Do **not** merge/publish/deploy Wave G unless separately authorized.

## Runtime boundary (locked)

- Rust central + React web + canonical Parquet historian + DataFusion SQL
- No Python in central/web request paths; no chatbot; no control writes
- Prefer small native Rust numerical deps compatible with lockfile (DataFusion **55** / Arrow **59** declared — verify `Cargo.lock` before coding)
- Python may stay offline research oracle only (`tools/wattlab_export/`, scripts) — do **not** promote `scripts/eplus_dump_clustering_export.py` zero-fill KMeans into product
- No ONNX / GPU / graph DB / distributed query without measured need

## Actual vs promised (recheck on tip before G0 closes)

| Area | Current product truth (recheck) | Wave G target |
|------|----------------------------------|---------------|
| Overview | Rules/analytics matrices; no ML/Physics column | Typed **ML / Physics** states + evidence drilldown |
| Engineering bundle | `openfdd_engineering_bundle_v1`; historically weak feature catalog / placeholders | **EnergyPlus calibration** purpose as primary download; research bundle separate |
| Offline clustering | `eplus_dump_clustering_export.py` descriptive + example KMeans | Not product ML |
| Rules | `crates/fdd_sql` / registry — stay intact | Hybrid compares on eligible periods; rules ≠ ground truth |
| Families | Many equipment types in Overview | **AHU+VAV slice first**; others show applicability/readiness only |

Proposal inspected commit `40ac0664` (2026-09-05). **Recheck** `engineering_bundle.rs`, `OverviewPopulated.tsx`, analytics routes, capability ledger against tip before editing.

## Child revs (one concern each)

| Rev | Concern | Prove |
|-----|---------|-------|
| **3.3.37** | Semantic applicability + versioned manifests | AHU/VAV applicable with reasons; heat-pump/etc. explicit unavailable; FDD-ON crosswalk only where verified |
| **3.3.38** | Shared feature pipeline | Same pipeline train+score; typed Parquet features; missing ≠ zero; unit boundary versioned |
| **3.3.39** | Regimes + deviation | Real fit/score; persisted artifacts; chronological splits + purge; novelty/OOD states |
| **3.3.40** | Physics residuals | Mixing + VAV sensible with gates; poorly conditioned → unavailable; no unique stuck-valve from one residual |
| **3.3.41** | Overview integration | Column states (not_run/training/normal/anomaly/N/A/…); job id run/train; cached reads; charts off Overview |
| **3.3.42** | Exports | EnergyPlus calibration bundle contents from **actual** available evidence; research bundle for ML audit; readiness from validated files |

## Stress / acceptance (Wave G)

| Tier | Role |
|------|------|
| Unit / contract / synthetic-59 | **Required** each child |
| Independent labeled public AHU/VAV set | Required for research claims; else document blocker and **disable** those claims |
| Railway smoke | Only after image-shipping tips; hybrid endpoints + Overview state |
| Soft-OPEN full Railway | Qualifies **OT hub**, not hybrid science |

Required test themes (from mission): unit conversions, missing roles, opaque ids, incomplete topology, duplicates/DST/gaps, train/test leakage, poorly conditioned mixing, no-training-data, unsupported family, save/load score parity, stale invalidation, cancel/restart, cross-building isolation, Overview freshness, export energy conservation, healthy→false-positive transitions.

## Out of scope until first slice gates pass

- Additional equipment families beyond AHU/VAV (beyond N/A chrome)
- Claiming Guideline 14 / full FDD-ON conformance / production ML readiness
- OT Modbus/MQTT soft-OPEN work (Waves D–F)
- Control writes, Python sidecar, chat UI

## Research grounding (synthesis, not prescription)

- Reproducibility of ML-based HVAC FDD (arxiv 2508.00880)
- ORNL fault behavior vs impact (read full OSTI PDF before detailed claims)
- FDD-ON (arxiv 2607.29657) — structure motivation only
- DataFusion docs — verify against pinned crate versions
