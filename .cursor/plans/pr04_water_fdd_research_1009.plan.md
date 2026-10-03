---
name: "PR-04 Water FDD research #1009"
overview: "Research and prioritize water-system / chiller-plant FDD rules; ship prioritized backlog doc and close #1009."
todos:
  - id: pr04-survey
    content: "Survey existing chiller/water rules in registry + cookbooks"
    status: pending
  - id: pr04-prioritize
    content: "Write prioritized backlog (P0/P1/P2) with roles required and gaps"
    status: pending
  - id: pr04-pr
    content: "Docs PR under docs/rules or docs/modeling; merge; close #1009"
    status: pending
isProject: false
---

# PR-04 — Water-system FDD research (#1009)

**Parent:** [`patch_all_open_issues_master.plan.md`](patch_all_open_issues_master.plan.md)  
**Branch:** `docs/water-chiller-fdd-priority-1009`  
**Closes:** #1009  
**Models:** design=`claude-sonnet-5-5-high` · write=`composer-2.5-fast` · CI watch=`muse-spark-1.3-high`

## Goal

Research deliverable (not full rule engine rewrite): prioritized chiller/water FDD backlog starting from existing registry + cookbook parity.

## Deliverable

- New doc e.g. `docs/rules/water-chiller-fdd-priority.md` with:
  - Existing rules that already apply to chwPlant / pumps
  - Missing high-value rules (sensor, delta-T, approach, staging)
  - Required Haystack/SQL roles
  - Explicit non-goals (no vendor hardcoding)

## Local verify

Doc cross-links to cookbook paths; no product code unless a tiny registry comment is needed.
