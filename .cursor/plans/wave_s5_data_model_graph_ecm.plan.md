---
name: Wave S5 data model graph ECM
overview: "Bounded tip after S2/S3: fix DM-01..10 graph/tenant defects, engineering quantities + ECM adapter, Pages docs, model stress gate for S4 FQ. Smoke after GHCR; FQ only on S4."
todos:
  - id: s5-dm-p1
    content: "Fix DM-01/02/03 (reproduced) + permanent regressions"
    status: pending
  - id: s5-dm-p1-source
    content: "DM-04 stamped types; DM-05 tenant storage; DM-06 route matrix"
    status: pending
  - id: s5-sparql-rdf
    content: "DM-07/08 SPARQL bindings + parser allowlist; DM-10 projection"
    status: pending
  - id: s5-eq-vocab
    content: "Engineering quantity vocab/shapes + package persistence"
    status: pending
  - id: s5-ecm-adapter
    content: "Typed adapter to open_fdd.ecm_engineering (fan/schedule/kw_ton)"
    status: pending
  - id: s5-pages
    content: "GitHub Pages modeling/ECM docs + jekyll checks"
    status: pending
  - id: s5-stress-wire
    content: "Model/ECM gate + 25b executed-check fix; CI only until S4 FQ"
    status: pending
  - id: s5-ghcr-smoke
    content: "VERSION tip PR → GHCR → re-pin → smoke (not FQ)"
    status: pending
isProject: false
---

# Wave S5 — data model, graph, engineering quantities

**Handoff:** [wave_s_data_model_graph_review_handoff.md](wave_s_data_model_graph_review_handoff.md)  
**Evidence:** [wave_s_data_model_evidence.md](wave_s_data_model_evidence.md)  
**Parent:** Wave S master. **Depends on:** S1 FQ done; S2 ADR + Camber lock. **Coordinates with:** S3 PyPI M&V (do not fork calculators). **Feeds:** S4 FQ (model/ECM gate must be wired before S4 MEGA).

## Boundaries

- One agent; no local heavy Rust/docker builds on bensbench (CI owns cargo).
- Do not launch an extra Railway FQ MEGA for this handoff — smoke after this tip; FQ on **S4**.
- Do not alter real customer models for fixtures.
- Python ECM stays outside product HTTP path.
- M&V UI (Metering radio) lands primarily on **S4** with SQL twins; S5 ships API/vocab.

## Exit

- DM-01..10 each have disposition + evidence row (PASS or visible BLOCKED/N/A).
- Engineering vocab + at least one end-to-end ECM adapter test green in CI.
- Pages build checks for new docs.
- Model/ECM gate referenced from stress runner; 25b rejects unexecuted BLOCKED required sets.
- Tip GHCR pinned; smoke only; evidence matrix updated.
