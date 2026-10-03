---
name: "PR-14 Gate39 MQTTS prove #1070"
overview: "Run ≥24h ACME MQTTS publish-ledger prove on tip; code PR only if tip defects found; Grok may re-prove after GHCR."
todos:
  - id: pr14-baseline
    content: "Day 0/1 — start ≥24h observation window NOW; record hub/edge tip SHA, health, edges freshness"
    status: pending
  - id: pr14-run-39
    content: "Run scripts/nightly-ot-bench/39_mqtts_gap_blame.sh / continuity gates; start ≥24h ledger window"
    status: pending
  - id: pr14-triage
    content: "If RTU/VAV silence or ledger gaps: file tip bug PR; else attach evidence and close #1070"
    status: pending
  - id: pr14-code-if-needed
    content: "Optional code PR only for proven tip defect; muse-spark watch CI"
    status: pending
  - id: pr14-handoff-grok
    content: "After final GHCR refresh, Grok re-proves and closes with artifacts"
    status: pending
isProject: false
---

# PR-14 — ACME MQTTS gate39 prove (#1070)

**Parent:** [`patch_all_open_issues_master.plan.md`](patch_all_open_issues_master.plan.md)  
**Branch:** only if code needed — `fix/mqtts-gate39-silence-<sha>`  
**Closes:** #1070 (via evidence and/or fix)  
**Models:** ops triage=`claude-sonnet-5-5-high` · code(if any)=`composer-2.5-fast` · CI watch=`muse-spark-1.3-high` · final prove=`Grok`

## Goal

Prove ≥24h publish-ledger continuity for ACME MQTTS on tip (currently referenced ~3.5.60 / `sha-6b35292` in issue — **re-resolve tip at run time**). Weather-only / missing RTU_01+VAV is RED until ledger proves otherwise.

## Default path (no code)

1. Backup / note hub pin.
2. Run gap blame + continuity harness from `scripts/nightly-ot-bench/`.
3. Store artifacts under `reports/…` (gitignored ok).
4. Close #1070 with links **or** leave open for Grok post-GHCR if window incomplete.

## Code path

Only if root cause is product tip (ingest reject, tenant filter, edge publish bug). Then normal PR loop; do not fold unrelated security auth-fail noise into this PR.
