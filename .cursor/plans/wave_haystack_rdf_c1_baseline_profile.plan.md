---
name: Haystack RDF C1 baseline profile
overview: "Reproduce export/ingest + gate-36 evaluator gaps; synthetic fixtures; versioned Haystack profile + JSON crosswalk; ADR decisions. No competing product tip required."
todos:
  - id: c1-repro-export
    content: "Reproduce current TTL/JSON export + BUILDING_100 audit findings with synthetic fixtures"
    status: pending
  - id: c1-repro-gate36
    content: "Reproduce 36_model_ecm_qualification evaluator gaps (inventory/ACL/SPARQL/ECM/rollup)"
    status: pending
  - id: c1-profile
    content: "Write ofdd_haystack_projection_vN profile + pinned defs versions + unknown-tag policy"
    status: pending
  - id: c1-crosswalk
    content: "Publish openfdd_data_model_v1 ↔ Haystack JSON/RDF field crosswalk"
    status: pending
  - id: c1-adr
    content: "Update ADR_data_model_graph — authority, identity, units, strict vs native export"
    status: pending
  - id: c1-reconcile
    content: "Reconcile DM-09/10 EQ Soft-OPEN rows into evidence matrix; no false PASS"
    status: pending
isProject: false
---

# C1 — Baseline and Haystack profile

**Parent:** [`wave_haystack_rdf_master.plan.md`](wave_haystack_rdf_master.plan.md)  
**HR foundations:** HR-02 (identity policy), HR-03/04 (profile), HR-05 (uncertainty rules), HR-12 (gap list for C5)  
**Depends on:** none (read-only + docs/fixtures)  
**Unlocks:** C2 schema choices, C3 projection contract

## Implementation tasks

1. **Synthetic fixtures** under `scripts/fixtures/haystack_rdf/` (or `tests/fixtures/…`):
   - Minimal site with AHU+VAV, ambiguous dual-role columns, missing `parent_ahu`, unknown unit, intentional exclusion.
   - Independent expected answers (JSON) — not generated from exporters under test.
   - Do **not** commit full `data_model_BUILDING_100.*` from Downloads.
2. **Reproduce export baseline** at current HEAD:
   - Trace `edge/src/csv_ingest/data_model_ttl.rs`, `frontend/web/src/api/dataModelTurtle.ts`, `mappingApi.ts` `openfdd_data_model_v1`.
   - Record: no Haystack IRIs in triples despite `hs:` prefix (custom RDF), diagnostics omitted from TTL.
3. **Reproduce gate-36 gaps** in `scripts/nightly-ot-bench/36_model_ecm_qualification.sh` + `scripts/qualification/write_manifest.py`:
   - HTTP 200 inventory without nonempty assert
   - Tenant B login without own-model / reverse B→A
   - SPARQL POST without query body; non-200 as PASS
   - ECM import-only
   - Rollup ignores required BLOCKED
   - File gap list into C5; do not “fix” gate 36 in C1.
4. **Profile document** `docs/modeling/haystack-rdf-profile.md` (name may adjust):
   - Named version `ofdd_haystack_projection_v1` (or bump if already narrow)
   - Pinned Haystack defs library URI/version
   - Marker/`ph:hasTag`, typed literals, refs, blank-node policy
   - Unknown tags → omit from strict projection + projection report
   - Open-FDD extension namespace (never mint into Haystack/Brick)
   - Unit-on-value vs point `unit` metadata distinction
5. **Crosswalk** `docs/modeling/data-model-json-rdf-crosswalk.md`:
   - Every `openfdd_data_model_v1` field ↔ RDF/JSON direction
   - Explicit lossy omissions for strict Haystack projection
   - Supported import/export directions table (none advertised without a test plan in C3)
6. **ADR update** `docs/architecture/ADR_data_model_graph.md`:
   - One authority per tenant/site revision
   - Strict vs native export
   - Identity/encoding rules (tie DM-01/02)
   - Central SPARQL: unavailable until C4 delivers — keep honesty

## Permanent tests (C1 ships fixtures + doc checks)

| Test | Command / CI | Expected |
| --- | --- | --- |
| Fixture schema present | `test -f` in docs Pages or tiny pytest | files exist |
| Profile links resolve | `docs-pages.yml` jekyll / link check if wired | build green |
| Crosswalk lists all advertised directions | manual review checklist in PR | no orphan claims |

No product VERSION tip required unless ADR/docs need Pages publish only.

## Stress / evidence

- Artifacts: `reports/haystack_rdf_c1_baseline_<UTC>/` — exporter SHA, triple counts on synthetic, gate-36 gap notes.
- Not a qualification pass.

## Docs

- ADR, profile, crosswalk, update `docs/modeling/consumer-route-matrix.md` capability honesty row.
- Point `AGENTS.md` / package-authoring at profile when published.

## Rollback

- Docs/fixtures only — revert PR; no runtime change.
- Do not weaken existing DM PASS rows.

## Exit criteria

- [ ] Synthetic fixtures + expected answers merged
- [ ] Gate-36 gap list filed for C5
- [ ] Profile + crosswalk + ADR decisions merged
- [ ] Evidence matrix Soft-OPEN rows updated (not closed)
- [ ] C2 may start schema design against locked profile
