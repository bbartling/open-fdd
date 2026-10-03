---
name: Haystack RDF C3 projection exports
overview: "Real Haystack profile projection from native metadata; centralized serialization; every advertised JSON/RDF import/export direction; HR-03/04/05."
todos:
  - id: c3-central-export
    content: "Authorize backend export path; SPA/agents consume it (parity if dual impl)"
    status: pending
  - id: c3-strict-native
    content: "Strict Haystack projection + native export + omission/projection report"
    status: pending
  - id: c3-directions
    content: "Implement/test every documented import/export direction"
    status: pending
  - id: c3-semantics
    content: "Independent RDFLib parse + pinned defs + graph constraints/SHACL"
    status: pending
  - id: c3-mapping-quality
    content: "Ambiguity/unknown-unit/missing-parent fixtures — no invented facts"
    status: pending
  - id: c3-tip-smoke
    content: "VERSION tip → GHCR → smoke; keep openfdd_data_model_v1 compatible"
    status: pending
isProject: false
---

# C3 — Semantic projection and exports

**Parent:** [`wave_haystack_rdf_master.plan.md`](wave_haystack_rdf_master.plan.md)  
**Depends on:** C1 profile + C2 native metadata  
**HR:** HR-03 Haystack semantics, HR-04 Projection fidelity, HR-05 Mapping quality  
**Prior:** DM-10 narrow PASS → full crosswalk Soft-OPEN; JSON-PARITY Soft-OPEN

## Implementation tasks

1. Prefer **centralized** authorized export in central (or shared Rust lib used by central) over dual TS/Rust forever.
   - During migration: independent parse + semantic equivalence tests against same contract.
2. Project from **native metadata only** (one authority).
3. Strict profile:
   - site/equip/point types, `ph:hasTag` markers, typed literals, refs
   - false/null markers must not become present markers
   - unknown tags omitted + projection report
   - no invented Haystack defs from SQL roles / column splits
4. Preserve mapping uncertainty in native + diagnostics in export where profile allows; never promote guessed parent to fact.
5. Keep `openfdd_data_model_v1` inventory download compatible **or** version replacement with tested migration.
6. If Haystack JSON interchange is advertised in C1 crosswalk — implement and test; else do not document it.

## Permanent tests

| ID | Approach | Command | Expected |
| --- | --- | --- | --- |
| HR-03 parse | RDFLib/oxigraph independent parse of exported TTL | pytest under `tests/` or `scripts/` | valid graph; pinned defs resolve |
| HR-03 markers | false/null marker fixtures | rust + pytest | markers absent |
| HR-03 dangling | forbidden dangling refs | rust | fail closed per profile |
| HR-04 iso | compare graph meaning modulo order/bnodes | pytest isomorphism helper | declared fields present; omissions listed |
| HR-04 directions | each import/export path | parameterized tests | round-trip only where claimed lossless |
| HR-05 ambiguity | two columns → one FDD role | fixture | FDD readiness ≠ syntax PASS |
| HR-05 parent | null parent_ahu | fixture | warning visible; no name inference |
| Parity | TS vs Rust exporter if both live | vitest + rust | semantic equivalence |

**CI:** extend Rust + frontend + Python jobs. Discover exact job names from `.github/workflows/` when executing (do not invent green history).

## Stress / smoke

- Smoke: download TTL/JSON for synthetic tenant; RDFLib parse in CI artifact step optional.
- Full gate-36 profile acceptance deferred to C5/C6.

## Docs

- Update crosswalk “implemented” column
- `docs/modeling/data_model_ttl.md`, consumer-route-matrix export rows
- Never claim full Haystack server or lossless round-trip without evidence

## Rollback criteria

- Revert tip; `openfdd_data_model_v1` still serves prior inventory shape
- Strict projection failures must not break ZIP import (C2 invariant)

## Exit criteria

- [ ] Strict + native exports from native metadata
- [ ] HR-03/04/05 permanent tests green in CI
- [ ] All **advertised** directions tested
- [ ] Tip smoke evidence recorded
- [ ] C4 unblocked
