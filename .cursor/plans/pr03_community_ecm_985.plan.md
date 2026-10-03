---
name: "PR-03 Community ECM review #985"
overview: "Ship a clear community call-for-review for ECM/engineering workbooks and close #985."
todos:
  - id: pr03-audit-docs
    content: "Locate current ECM docs/workbook entrypoints (docs/ecm, PyPI open_fdd.ecm_engineering)"
    status: pending
  - id: pr03-write-call
    content: "Add/refresh community review section with scope, how to test, feedback channel"
    status: pending
  - id: pr03-pr-ci
    content: "Docs PR; muse-spark watch; merge docs — KEEP #985 open as help wanted"
    status: pending
isProject: false
---

# PR-03 — Community ECM review (#985)

**Parent:** [`patch_all_open_issues_master.plan.md`](patch_all_open_issues_master.plan.md)  
**Branch:** `docs/community-ecm-review-985`  
**Closes:** (docs improve only — **do not close #985**; standing community invitation)  
**Models:** code=`composer-2.5-fast` · CI watch=`muse-spark-1.3-high`

## Goal

Make the engineering calculations / ECM workbook review path discoverable for external reviewers (help wanted / good first issue).

## Work

- Point to [`docs/ecm/README.md`](../../docs/ecm/README.md) and PyPI `open_fdd.ecm_engineering`.
- Document how to run a minimal workbook check and where to file feedback (issue comments / PR).
- No product runtime change; docs-only preferred.

## Local verify

Markdown links resolve; no secrets. Optional: `pytest` on existing ECM tests if docs claim commands.
