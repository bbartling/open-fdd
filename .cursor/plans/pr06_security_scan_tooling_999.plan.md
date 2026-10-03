---
name: "PR-06 / #1102 TAKEOVER — security profiles + #999"
overview: "Cursor takes over Codex draft #1102. Finish Nessus A08 + local pytest, undraft, merge. Closes #999 tooling path."
todos:
  - id: pr06-takeover
    content: "Work in .worktrees/security-post5d on security/post5d-profile-qualification"
    status: in_progress
  - id: pr06-nessus
    content: "Finish dirty Nessus importer A08 + unit tests; local pytest tests/security"
    status: pending
  - id: pr06-ready
    content: "Push, gh pr ready 1102, watch Actions, merge when green"
    status: pending
  - id: pr06-followons
    content: "After merge: optional follow-on PRs for A01–A04/A06–A07 compose/Caddy/nginx/ZAP"
    status: pending
isProject: false
---

# Take over #1102 (was Codex) + #999

**Parent:** [`patch_all_open_issues_master.plan.md`](patch_all_open_issues_master.plan.md)  
**Worktree:** `.worktrees/security-post5d/`  
**Branch:** `security/post5d-profile-qualification`  
**PR:** https://github.com/bbartling/open-fdd/pull/1102  

## Spec

Follow [`openfdd_agent_spec/PR_PROTOCOL.md`](../../openfdd_agent_spec/PR_PROTOCOL.md) — **local pytest green before push/undraft**. Agent takeover rules in that file + AGENTS **0c**.

## Finish now

1. Complete `scripts/security/nessus/import_nessus_report.py` expectation/DTD/bounds work already dirty.
2. `python3 -B -m pytest tests/security -q` in the worktree.
3. Commit, push, `gh pr ready 1102`, watch Actions, merge.
4. Soft-OPEN: licensed live Nessus scan remains blocked without license — tooling merge is still valid.
5. **Handoff:** after GHCR refresh, **Grok bot** runs live gates 25/25b/26 (+ optional Nessus). Cursor does not claim pen-test PASS from unit tests.