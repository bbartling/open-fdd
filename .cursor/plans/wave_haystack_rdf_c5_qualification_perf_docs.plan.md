---
name: Haystack RDF C5 qualification perf docs
overview: "Wire HR-01–HR-12 into gate 36 + write integrity; perf baselines; Pages/agent docs. HR-11/HR-12 primary."
todos:
  - id: c5-gate36
    content: "Rewrite 36_model_ecm_qualification required-set + semantic asserts"
    status: pending
  - id: c5-negatives
    content: "Permanent broken-fixture evaluator tests (HR-12)"
    status: pending
  - id: c5-perf
    content: "HR-11 seeded small/large measures on suitable host; caps first"
    status: pending
  - id: c5-docs
    content: "Pages, route matrix, skills, SESSION_LOG, BUG_REPORT Soft-OPEN row"
    status: pending
  - id: c5-ci
    content: "CI runs qualification negatives + frontend/rust/python slices"
    status: pending
isProject: false
---

# C5 — Qualification, performance, documentation

**Parent:** [`wave_haystack_rdf_master.plan.md`](wave_haystack_rdf_master.plan.md)  
**Depends on:** C1–C4 landed (or HR-10 Option B honesty in place)  
**HR:** HR-11 Performance, HR-12 Evaluator integrity; wires evidence for HR-01–HR-10  
**Prior:** STRESS-GATE Soft-OPEN; gate-36 source gaps from C1

## Implementation tasks

1. **Gate 36** `scripts/nightly-ot-bench/36_model_ecm_qualification.sh`:
   - Stable check IDs; explicit required-set contract
   - Nonempty inventory assert with known expected
   - Tenant A/B own-model + reverse path + owner-positive 404
   - SPARQL: real query body **or** separate honesty UNAVAILABLE ID (not feature PASS)
   - ECM: execute adapter math, not import-only
   - Rollup rejects required BLOCKED/N/A/SKIPPED/unknown
2. **`scripts/qualification/write_manifest.py`**: consume executed semantic results, fixture/candidate identities, artifacts.
3. **HR-12 negatives** (permanent):
   - malformed TTL, empty expected inventory, missing point/unit/ref, foreign data
   - stale candidate/hash, dropped checks, duplicate check IDs, timeout, absent artifact
   - Assert **nonzero** process exit + nonqualifying final manifest
4. **HR-11 perf**:
   - Define metadata size/node/query limits first (ADR)
   - Seed small + large multi-site synthetic models
   - Record counts, cold/warm p50/p95, peak RSS, cache rebuild, bounded concurrency
   - Suitable host (not Pi); skipped large run ⇒ no large-scale claim
5. **Docs close**:
   - GitHub Pages nav/build (`docs-pages.yml`)
   - package authoring, profile, crosswalk, consumer-route-matrix
   - agent guides/skills; `openfdd_agent_spec/SESSION_LOG.md` entry when executing
   - `BUG_REPORT_WAVE_P.md` Soft-OPEN `wave-haystack-rdf`
   - `MILESTONES.md` implementation vs verification columns (no release claim)

## Permanent tests / CI commands (discover exact workflow names at execute time)

| Slice | Likely command | Expected |
| --- | --- | --- |
| Evaluator negatives | `pytest tests/qualification/…` or sibling of `test_afdd_evaluator_negatives.py` pattern | all broken fixtures fail closed |
| Gate 36 dry | `ARTIFACT_DIR=… bash scripts/nightly-ot-bench/36_model_ecm_qualification.sh` against disposable | required-set executed |
| Rust/UI/Py | existing CI jobs + new tests from C2–C4 | green |
| Pages | `.github/workflows/docs-pages.yml` | new HTML present |
| Perf | documented bench script → `docs/operations/perf/haystack_rdf_hr11.md` | table filled or PARTIAL honest |

Wire gate into `run_railway_hub_stress.sh` required list only when evaluator negatives prove fail-closed (do not require live OT).

## Stress evidence

- CI + local disposable fixtures for portable proof
- Enhanced full qualification window reserved for **C6**
- Keep security gates (25/25b/ZAP/etc.) enabled

## Rollback criteria

- Harness-only revert must not leave required-set weaker than pre-C5
- If gate 36 becomes stricter mid-tip, Soft-OPEN rows stay visible until product tip catches up

## Exit criteria

- [ ] HR-12 negatives green in CI
- [ ] Gate 36 required-set contract documented + implemented
- [ ] HR-11 baseline table or honest PARTIAL
- [ ] Docs/Pages/agent updates merged
- [ ] C6 may schedule candidate enhanced window
