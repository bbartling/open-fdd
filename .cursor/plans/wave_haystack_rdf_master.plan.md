---
name: Wave Haystack RDF master
overview: "Executable master for Haystack RDF interoperability (HR-01–HR-12). Preserves ZIP/JSON; extends native metadata; versioned projection; viewer/ECM/graph; gate-36 evaluator integrity. Planning frozen until usage renews; implementation starts when this plan is run."
todos:
  - id: hr-c1-baseline
    content: "C1 Baseline + Haystack profile/crosswalk/ADR (HR foundations)"
    status: pending
  - id: hr-c2-persist
    content: "C2 Compatible metadata persistence (HR-01/02/07)"
    status: pending
  - id: hr-c3-projection
    content: "C3 Semantic projection + JSON/RDF exports (HR-03/04/05)"
    status: pending
  - id: hr-c4-viewer-ecm
    content: "C4 Model viewer + ECM adapter + graph/SPARQL honesty (HR-06/08/09/10)"
    status: pending
  - id: hr-c5-qual
    content: "C5 Gate-36 evaluator + perf + docs (HR-11/12 + matrix)"
    status: pending
  - id: hr-c6-rollout
    content: "C6 Candidate tip → smoke → enhanced FQ evidence + closeout"
    status: pending
isProject: true
---

# Wave Haystack RDF — master

**Status:** activated under [`patch_all_open_issues_master.plan.md`](patch_all_open_issues_master.plan.md) as Track D (PR-02 C1, PR-07…PR-11 C2–C6). Execute child plans in order when that master runs.

**Requirements SoT:** [`openfdd_agent_spec/HAYSTACK_RDF_ROLLOUT.md`](../../openfdd_agent_spec/HAYSTACK_RDF_ROLLOUT.md) (HR-01–HR-12)  
**Planning entry:** [`.cursor/agents/haystack-rdf-implementation-handoff.md`](../agents/haystack-rdf-implementation-handoff.md)  
**Graph ADR:** [`docs/architecture/ADR_data_model_graph.md`](../../docs/architecture/ADR_data_model_graph.md)  
**Prior DM/EQ evidence:** [`.cursor/plans/wave_s_data_model_evidence.md`](wave_s_data_model_evidence.md)

## Ownership reconcile (do not fork)

| Prior ID | Prior home | Haystack owner | Disposition |
| --- | --- | --- | --- |
| DM-01..03 | S5 tip PASS | C2/C3 regressions | Keep tests; extend for HR-02 |
| DM-04 stamps | Soft-OPEN | C2 | Package stamps → native metadata |
| DM-05 tenant storage | Soft-OPEN | C2 + C4 (HR-06) | Server-derived scope |
| DM-06 route matrix | PASS (SPARQL unavailable) | C4 HR-10 | Honesty until central SPARQL ships |
| DM-07/08 SPARQL tip | V5 PASS (edge) | C4 HR-10 | Edge ≠ central package graph |
| DM-09 PERF PARTIAL | S5/W4 | C5 HR-11 | Measure before claim |
| DM-10 projection narrow PASS | W4 | C1 + C3 HR-03/04 | Full profile + crosswalk Soft-OPEN → this wave |
| EQ-VOCAB / ECM-ADAPT tip PASS | W4 | C4 HR-08 | Keep; add model→calc fixture math |
| EQ-PERSIST Soft-OPEN | S5 | C2 HR-01/07 | Persist engineering quantities |
| SEC-ML Soft-OPEN | S5 | C4 HR-06 | Full lifecycle ACL |
| JSON-PARITY Soft-OPEN | S5 | C1 + C3 HR-04 | Field crosswalk |
| STRESS-GATE Soft-OPEN | S5 | C5 + C6 HR-12 | Gate 36 required-set + negatives |
| UI-MV (Metering) | S4 | **out of scope** | Do not absorb into Haystack wave |
| Wave U security spine / ACME AFDD | Wave U | **parallel; not blocked** | No competing master |

**S5/V5 residual:** [`wave_s5_data_model_graph_ecm.plan.md`](wave_s5_data_model_graph_ecm.plan.md) and [`wave_u_v5_s5_dm_ecm.plan.md`](wave_u_v5_s5_dm_ecm.plan.md) remain historical Soft-OPEN pointers. **New product work for DM-09/10 fullness, EQ-PERSIST, SEC-ML, JSON-PARITY, UI model viewer, and gate-36 integrity is scheduled here**, not as a second competing S5 tip.

## Boundaries (hard)

- Preserve `openfdd_package_v1` ZIP + compact JSON maps; no fabricated metadata for old packages.
- Telemetry/FDD stay Parquet/DataFusion; Python stays external ECM/agent/CI.
- One authority per tenant/site revision; exports derive from native metadata.
- No local heavy Rust/`docker build` on bensbench — CI/GHCR owns images.
- Synthetic public fixtures only (no `/home/ben/Downloads` BUILDING_100 commit).
- Mid-tips = smoke only; enhanced FQ evidence only on C6 after required-set green.
- Do not claim Haystack HTTP server certification from RDF export alone.

## Rollout order (execute in sequence)

```text
C1 baseline/profile  →  C2 persistence  →  C3 projection/exports
        →  C4 viewer/ECM/graph  →  C5 qual/perf/docs  →  C6 candidate/FQ closeout
```

| Order | Child plan | Primary HR | Tip style |
| --- | --- | --- | --- |
| 1 | [`wave_haystack_rdf_c1_baseline_profile.plan.md`](wave_haystack_rdf_c1_baseline_profile.plan.md) | foundations for all | docs/ADR + fixtures (may ship without VERSION) |
| 2 | [`wave_haystack_rdf_c2_metadata_persistence.plan.md`](wave_haystack_rdf_c2_metadata_persistence.plan.md) | HR-01, HR-02, HR-07 | VERSION tip PR → GHCR → smoke |
| 3 | [`wave_haystack_rdf_c3_projection_exports.plan.md`](wave_haystack_rdf_c3_projection_exports.plan.md) | HR-03, HR-04, HR-05 | VERSION tip PR → GHCR → smoke |
| 4 | [`wave_haystack_rdf_c4_viewer_ecm_graph.plan.md`](wave_haystack_rdf_c4_viewer_ecm_graph.plan.md) | HR-06, HR-08, HR-09, HR-10 | VERSION tip PR → GHCR → smoke |
| 5 | [`wave_haystack_rdf_c5_qualification_perf_docs.plan.md`](wave_haystack_rdf_c5_qualification_perf_docs.plan.md) | HR-11, HR-12 + wire-all | harness PR; CI; perf host |
| 6 | [`wave_haystack_rdf_c6_candidate_rollout.plan.md`](wave_haystack_rdf_c6_candidate_rollout.plan.md) | all HR evidence closeout | backup → pin → smoke → enhanced gate-36 window |

## HR → child coverage matrix

| HR | Title | Children | Permanent tests (targets) | CI / stress | Rollback |
| --- | --- | --- | --- | --- | --- |
| HR-01 | Package compatibility | C2, C3 | Rust package import + append fixtures; analytics golden unchanged | `cargo test` package; gate 36 package rows | Revert tip; old ZIPs still import |
| HR-02 | Identity | C1, C2 | Unit: Unicode/quotes/`enc_`/dup IDs/tenants | vitest + rust dm01/02 extended | Reject bad IDs; no silent merge |
| HR-03 | Haystack semantics | C1, C3 | Independent RDFLib parse + pinned defs + SHACL/constraints | pytest RDF; rust projection | Strict projection omit unknowns |
| HR-04 | Projection fidelity | C3 | Isomorphism modulo bnodes; all import/export dirs | rust+pytest+TS exporter parity | Version export; keep v1 inventory |
| HR-05 | Mapping quality | C3, C4 | Ambiguous role / missing parent / unknown unit fixtures | gate 36 mapping diagnostics | Never invent topology |
| HR-06 | Authorization | C4 | Two-tenant A↔B + owner-positive 404 control | security harness + gate 31/36 | Fail closed; no cross-tenant cache |
| HR-07 | Revision lifecycle | C2 | Atomic fail, conflict, restart, cache stale, rollback rehearsal | integration + smoke | Historian untouched; metadata rollback |
| HR-08 | Engineering | C4 | model→`open_fdd.ecm_engineering` known math | pytest adapter | Unready ≠ fake PASS |
| HR-09 | UI | C4 | Vitest + browser hierarchy/downloads/XSS text | frontend CI + Playwright/Vitest browser | Keep MappingPage edits |
| HR-10 | Graph capability | C4 | Real SPARQL or honest UNAVAILABLE | gate 36 SPARQL row with query body | Feature ID ≠ honesty ID |
| HR-11 | Performance | C5 | Seeded small/large; p50/p95/RSS | perf doc + optional host bench | Cap queries; skip≠claim |
| HR-12 | Evaluator integrity | C5, C6 | Broken fixtures → nonzero + nonqualifying | `tests/qualification` + gate 36 | Never weaken required-set |

## Evidence table (fill during execution — leave empty until run)

| HR | Tip SHA / semver | Test command | Artifact path | Status |
| --- | --- | --- | --- | --- |
| HR-01 | | | | pending |
| HR-02 | | | | pending |
| HR-03 | | | | pending |
| HR-04 | | | | pending |
| HR-05 | | | | pending |
| HR-06 | | | | pending |
| HR-07 | | | | pending |
| HR-08 | | | | pending |
| HR-09 | | | | pending |
| HR-10 | | | | pending |
| HR-11 | | | | pending |
| HR-12 | | | | pending |

## First executable package

**C1** — dependencies satisfied: ADR + exporters + S5 evidence already exist; no product tip required to write the versioned Haystack profile, JSON field crosswalk, synthetic fixtures, and reproduce gate-36 evaluator gaps. Blocks nothing behind it except decision lock for C2/C3 schemas.

## Tracker updates (on execution, not now)

- Soft-OPEN row: `wave-haystack-rdf` in `BUG_REPORT_WAVE_P.md` / `WAVE_U_MASTER.md`
- `MILESTONES.md`: implementation vs verification vs release columns separate
- Do not pre-close DM/EQ Soft-OPEN rows; migrate disposition when C* evidence lands

## GH tracking

| Package | Issue |
| --- | --- |
| Master HR-01–HR-12 | [#997](https://github.com/bbartling/open-fdd/issues/997) |
| C1 baseline/profile | [#998](https://github.com/bbartling/open-fdd/issues/998) |
| C2 persistence | [#1000](https://github.com/bbartling/open-fdd/issues/1000) |
| C3 projection | [#1001](https://github.com/bbartling/open-fdd/issues/1001) |
| C4 viewer/ECM/graph | [#1002](https://github.com/bbartling/open-fdd/issues/1002) |
| C5 qual/perf/docs | [#1003](https://github.com/bbartling/open-fdd/issues/1003) |
| C6 candidate closeout | [#1004](https://github.com/bbartling/open-fdd/issues/1004) |

Checkboxes on each issue map to child-plan todos and HR rows.
