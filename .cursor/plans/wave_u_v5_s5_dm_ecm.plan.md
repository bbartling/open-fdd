---
name: Wave U V5 S5 DM ECM
overview: "S5 DM-07..10 SPARQL/PERF, EQ-VOCAB, ECM-ADAPT, Pages. Soft-OPEN wave-s5-dm-remainder. Smoke only."
todos:
  - id: v5-dm-sparql
    content: "DM-07/08 SPARQL bindings + allowlist (DM-09/10 residual PARTIAL)"
    status: completed
  - id: v5-eq-ecm
    content: EQ-VOCAB shapes + ECM adapter to open_fdd.ecm_engineering
    status: pending
  - id: v5-pages-smoke
    content: Pages docs + tip GHCR + Railway smoke (not FQ)
    status: pending
isProject: false
---

# V5 — S5 data model / ECM remainder

**Parent:** [`wave_u_remainder_patch_cycles.plan.md`](wave_u_remainder_patch_cycles.plan.md)  
**Child:** [`wave_s5_data_model_graph_ecm.plan.md`](wave_s5_data_model_graph_ecm.plan.md)

## Soft-OPEN closed or advanced

- `wave-s5-dm-remainder` — **PARTIAL**: DM-07/08 closed on Tip A; residual DM-09/10, EQ-VOCAB, ECM-ADAPT, Pages

## Work

1. Tip A (this tip): DM-07 exact IRI/literal SPARQL bindings + DM-08 parser allowlist / no empty-ok.
2. Later tips: DM-09/10, engineering vocab, ECM adapter, Pages.
3. Tip PR → GHCR → backup/re-pin → smoke. **No MEGA** (FQ is V6).

## Exit

- Evidence matrix rows for DM-07/08 PASS; DM-09/10 + EQ/ECM/Pages honest PARTIAL.
