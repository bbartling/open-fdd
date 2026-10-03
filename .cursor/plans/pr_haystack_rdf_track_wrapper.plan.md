---
name: "PR-02..11 Haystack RDF track wrapper"
overview: "Execute existing Haystack RDF C1–C6 plans as PR-02 and PR-07..PR-11; close #997–#1004 (except #999)."
todos:
  - id: hr-pr02-c1
    content: "PR-02 execute wave_haystack_rdf_c1 — close #998"
    status: pending
  - id: hr-pr07-c2
    content: "PR-07 execute wave_haystack_rdf_c2 — VERSION tip — close #1000"
    status: pending
  - id: hr-pr08-c3
    content: "PR-08 execute wave_haystack_rdf_c3 — close #1001"
    status: pending
  - id: hr-pr09-c4
    content: "PR-09 execute wave_haystack_rdf_c4 — pick SPARQL Option A or honest UNAVAILABLE — close #1002"
    status: pending
  - id: hr-pr10-c5
    content: "PR-10 execute wave_haystack_rdf_c5 — gate-36 harness — close #1003"
    status: pending
  - id: hr-pr11-c6
    content: "PR-11 execute wave_haystack_rdf_c6 — candidate smoke — close #1004 and master #997"
    status: pending
isProject: false
---

# Haystack RDF PR track (PR-02, PR-07…PR-11)

**Parent:** [`patch_all_open_issues_master.plan.md`](patch_all_open_issues_master.plan.md)  
**Master requirements:** [`wave_haystack_rdf_master.plan.md`](wave_haystack_rdf_master.plan.md) · SoT `openfdd_agent_spec/HAYSTACK_RDF_ROLLOUT.md`  
**Models:** design=`claude-opus-5-thinking-high` · code=`composer-2.5-fast` · critique=`claude-sonnet-5-5-high` · CI watch=`muse-spark-1.3-high`

## Mapping

| PR | Issue | Existing plan | Tip |
| --- | --- | --- | --- |
| PR-02 | #998 | [`wave_haystack_rdf_c1_baseline_profile.plan.md`](wave_haystack_rdf_c1_baseline_profile.plan.md) | docs/fixtures — may skip VERSION |
| PR-07 | #1000 | [`wave_haystack_rdf_c2_metadata_persistence.plan.md`](wave_haystack_rdf_c2_metadata_persistence.plan.md) | VERSION → GHCR smoke |
| PR-08 | #1001 | [`wave_haystack_rdf_c3_projection_exports.plan.md`](wave_haystack_rdf_c3_projection_exports.plan.md) | VERSION → smoke |
| PR-09 | #1002 | [`wave_haystack_rdf_c4_viewer_ecm_graph.plan.md`](wave_haystack_rdf_c4_viewer_ecm_graph.plan.md) | VERSION → smoke; **HR-10 Option B** (honest UNAVAILABLE); ACL uses PR-01 isolation |
| PR-10 | #1003 | [`wave_haystack_rdf_c5_qualification_perf_docs.plan.md`](wave_haystack_rdf_c5_qualification_perf_docs.plan.md) | harness/CI |
| PR-11 | #1004+#997 | [`wave_haystack_rdf_c6_candidate_rollout.plan.md`](wave_haystack_rdf_c6_candidate_rollout.plan.md) | candidate; enhanced FQ evidence optional until Grok |

## Execution rule

Open each child plan and execute its todos in order. Do **not** start C(n+1) product tip until C(n) PR is merged (C1 can parallel Track A). Use local OT only where child plan calls for it; full gate-36 window may wait for final GHCR + Grok.

## Note on #999

Issue #999 is **Security Scan Tooling** — handled by **PR-06**, not this track.
