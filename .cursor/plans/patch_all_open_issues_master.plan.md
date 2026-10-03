---
name: Patch all open GH issues master
overview: "Scope C — ship every open GitHub issue as PR trains from one IDE, including finishing Codex #1102/#999, local compile+tests+OT bench, merge to master, then GHCR refresh and Grok handoff."
todos:
  - id: wave0-lock
    content: "Wave 0 — no volume wipe; start #1070 24h window; single-IDE owns all branches including former Codex #1102"
    status: completed
  - id: track-a-mt
    content: "Track A — PR-01 MT isolation (#1088/#1089/#1090) then PR-05 CSV UX (#1087)"
    status: in_progress
  - id: track-b-docs
    content: "Track B parallel — PR-02 HR C1 (#998), PR-03 ECM (#985 keep open), PR-04 water FDD (#1009)"
    status: in_progress
  - id: track-c-sec
    content: "Track C — TAKE OVER Codex #1102 / #999 — finish security profile qualification PR and merge"
    status: in_progress
  - id: track-d-hr
    content: "Track D sequential — Haystack RDF C2→C6 (#1000–#1004) then close #997"
    status: pending
  - id: track-e-df
    content: "Track E — PR-12 DataFrame API + agent custom rules (#1078+#1010)"
    status: pending
  - id: track-f-hist
    content: "Track F — PR-13 historian / Haystack hisRead (#1017)"
    status: pending
  - id: track-g-field
    content: "Track G — PR-14 gate39 MQTTS prove (#1070); window already started"
    status: in_progress
  - id: merge-train
    content: "Merge train — green GH Actions → merge each PR onto master in dependency order (incl #1102)"
    status: pending
  - id: ghcr-refresh
    content: "Final GHCR refresh — newest-by-created pin + stack pull/up"
    status: pending
  - id: grok-handoff
    content: "Handoff to Grok — OT MEGA / hub stress, close issues with evidence"
    status: pending
isProject: true
---

# Patch all open GH issues — master plan

**Goal:** Close **all 18 open issues** via PR trains from **one IDE**, including finishing former Codex draft [#1102](https://github.com/bbartling/open-fdd/pull/1102) / [#999](https://github.com/bbartling/open-fdd/issues/999), local compile/tests + OT bench, merge everything into `master`, then one **GHCR refresh** and hand stress/closeout to **Grok**.

**Architecture:** Wave-1 parallel (MT security + docs/fixtures + finish #1102), then serial Haystack C2–C6, parallel DataFrame and historian lanes. Each PR: implement → local verify → open/ready PR → watch Actions → fix → merge.

**Change from earlier draft:** Codex is out of API budget — **do not exclude #1102**. Take over branch `security/post5d-profile-qualification` (worktree `.worktrees/security-post5d/`), finish remaining Astra findings that belong on that PR (esp. Nessus A08 WIP already dirty), undraft, merge when green. Later PRs may touch compose/caddy/nginx **after** #1102 lands, or land remaining A01–A04/A06–A07 as follow-on PRs in this same train.

## Global constraints

- Own **all** open branches from this IDE — including `#1102`. No competing Codex sessions.
- Never `docker compose down -v`, never delete `workspace/`, never print secrets.
- No local heavy `docker build` of stack images on bensbench — CI/GHCR owns product images.
- Product tips: bump workspace **patch** `VERSION` when operator-visible; mid-wave tips smoke only.
- Site identity: type/roles/registry only — no hardcoded fixture equipment selectors.
- Follow [`openfdd_agent_spec/PR_PROTOCOL.md`](../../openfdd_agent_spec/PR_PROTOCOL.md).

## Issue → PR map (all 18)

| Issue | PR | Track | Notes |
| --- | --- | --- | --- |
| #1088 #1089 #1090 | **PR-01** | A | One isolation PR — string-array filter leak + list-scope gate |
| #1087 | **PR-05** | A | After PR-01 |
| #998 | **PR-02** | B | Haystack C1 baseline |
| #985 | **PR-03** | B | ECM docs; keep issue open as help wanted |
| #1009 | **PR-04** | B | Water/chiller FDD research |
| #999 | **#1102** | C | **TAKE OVER** — finish + merge (was Codex) |
| #1000–#1004 + #997 | **PR-07…11** | D | Haystack C2–C6; #997 last |
| #1078 + #1010 | **PR-12** | E | DataFrame + agent custom rules |
| #1017 | **PR-13** | F | Historian + hisRead |
| #1070 | **PR-14** | G | ≥24h MQTTS prove |

## Track C — finish #1102 (was Codex)

Branch / worktree: `security/post5d-profile-qualification` · `.worktrees/security-post5d/`

Already on PR: policy doc, deployment profile evidence contract, trivy split-connector scope, tests.

**Finish now:**
1. Commit dirty Nessus importer hardening (A08) + unit tests in worktree.
2. Run `pytest tests/security -q` locally.
3. `gh pr ready 1102`; watch Actions; fix until green.
4. Merge #1102 → closes tooling path for #999 (Nessus license Soft-OPEN ok).
5. Remaining Astra A01–A04 / A06–A07 compose/Caddy/nginx/ZAP may be **follow-on PRs** in this train after merge (same IDE, no conflict).

## Wall-clock waves

```text
Wave 1: PR-01 + PR-02 + PR-03 + PR-04 + finish/merge #1102 ; #1070 window open
Wave 2: PR-05 + HR C2 + PR-12 start + historian L1
Wave 3–5: HR C3–C6, DF, historian L2/L3, gate39 evidence
Final: GHCR refresh → Grok MEGA
```

## Model routing

| Role | Model |
| --- | --- |
| Implement | `composer-2.5-fast` / `gemini-3.8-flash-high` |
| Critique | `claude-sonnet-5-5-high` |
| Watch Actions | `muse-spark-1.3-high` |
| Hard design | `claude-opus-5-thinking-high` |

## Success definition

- All 18 issues addressed (merged code/docs or evidence); **#1102 merged** (not left open).
- `master` green; GHCR tip refreshed; Grok owns post-refresh MEGA / issue close comments.
