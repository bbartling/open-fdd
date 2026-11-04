# Grok cloud orchestrator — 4.0.11 audit patch train

Paste this checklist to spawn **one Cursor cloud agent per PR**. Each agent reads `AGENTS.md`, `openfdd_agent_spec/AGENTS.md`, `openfdd_agent_spec/PR_PROTOCOL.md`, the matching skill, and its rows in [`patch_trains/4.0.11_audit_ledger.md`](patch_trains/4.0.11_audit_ledger.md). **No secrets, lab ids, host IPs, or `.env` contents in prompts or commits.**

## Rules (all agents)

- Exactly **one PR** per slot; PR body states problem → behavior → source → closing test. Use **“Fixes part of #N”** — never “Closes #N”.
- **Do not** bump `VERSION` or Cargo versions (PR-R only). **Do not merge** your own PR.
- Watch **`gh pr checks`** and CodeRabbit on the exact head until green; fix on the same branch.
- DB/scientific work runs in existing CI workflows (`sql-qual-c3a.yml`, `c3c-sqlqual-11-12a.yml`, `si-parity.yml`, `stack-crate-tests-pr.yml`, `rust-ci.yml`) — not the owner database.
- Never drop workflow triggers or tests; never refresh frozen IP goldens or add waivers to pass.
- Rust: fmt + clippy clean; no allow/expect/unsafe/unwrap on product paths. Timescale-only historian. No Python/Node in central image.
- Keep security reproduction details **private**; PR10 and public docs stay generic.
- One heavy runner/scanner at a time on the owner host; cloud agents run **targeted** tests only.

## Merge order

1. **PR0** merges first (tooling import + ledger + this handoff).
2. **Parallel:** PR1, PR2, PR9, PR10, PR3, PR4.
3. **PR8** after PR2. **PR5** after PR4. **PR6** after PR5. **PR7** after PR6.
4. **PR-R** last (single 4.0.10 → 4.0.11 bump + spec/skills sync).

After each merge: Grok runs `gh pr checks`, squash-merges with `--delete-branch`, updates the ledger row (`commit`, `CI run`), ticks the box below, and comments evidence on linked issues (close only when closing test + current-image proof are met).

## PR checklist

- [x] **PR0** — [#1518](https://github.com/bbartling/open-fdd/pull/1518) @ `27af6578`: tooling import, `4.0.11_audit_ledger.md`, this handoff. **Fixes part of #1509.**
- [x] **PR1** — [#1483](https://github.com/bbartling/open-fdd/pull/1483) @ `693b2686`: exact-name test selection. **Fixes part of #1423 / #1406 (tooling slice).**
- [x] **PR2** — [#1481](https://github.com/bbartling/open-fdd/pull/1481) @ `576c1eee`: full SQL-QUAL tuner matrix + all-column analytics incl. `fault_flag`; SV-RANGE A–D. **Fixes part of #1284.**
- [x] **PR3** — [#1522](https://github.com/bbartling/open-fdd/pull/1522) @ `d2ad0d04`: ingest bundle #1501, #1500, #1499, #1423, #1403. **Fixes part of #1401.**
- [x] **PR4** — [#1520](https://github.com/bbartling/open-fdd/pull/1520) @ `070cbe19`: graph model + point identity #1508, #1516, #1441. 
- [x] **PR5** — [#1524](https://github.com/bbartling/open-fdd/pull/1524) @ `4d2aa2fe`: SI units #1513, #1406, #1407, #1405.
- [x] **PR6** — [#1525](https://github.com/bbartling/open-fdd/pull/1525) @ `0c38f0e8`: UI behavior #1517, #1510, #1511, #1512, #1497 (**residual:** Charts calendar pickers).
- [x] **PR7** — [#1526](https://github.com/bbartling/open-fdd/pull/1526) @ `7df8e1d8`: UI workflows #1514, #1515, CSV export proof.
- [x] **PR8** — [#1523](https://github.com/bbartling/open-fdd/pull/1523) @ `5bb357c5`: FDD SQL science #1437, #1439, #1404, #1408.
- [x] **PR9** — [#1521](https://github.com/bbartling/open-fdd/pull/1521) @ `98f7eb42`: capture + C3c #1440, #1444.
- [x] **PR10** — [#1519](https://github.com/bbartling/open-fdd/pull/1519) @ `7e80d064`: nosniff + deliberate bare-central `security.txt`.
- [ ] **PR-R** — 4.0.10 → **4.0.11** bump; #1502 residual guards; `openfdd_agent_spec` + skills sync; ledger disposition for #1284 / #1401 (umbrellas stay open until current-image proof).

## Post-train (owner host, not cloud)

- [ ] Wait for GHCR central (+ MCP) publish on PR-R merge; resolve newest image by OCI `created` (`./scripts/ghcr_newest_by_created.py openfdd-central`).
- [ ] Isolated owned qualification on that `sha-*` (central-only recipe, static model probe PASS, finite passive ZAP, Playwright `/app/`, offline qualification roster, security discovery) — one workload at a time; append receipts to private review dir and ledger **current-image proof** column.
- [ ] If qualification passes: `./scripts/openfdd_local_repin.sh sha-X`, `./scripts/openfdd_demo_gate.sh`, health check. No `down -v`, no prune, no DB reset.
- [ ] Cleanup stale train branches/worktrees; delete disposable creds and probe artifacts; final issue disposition pass on every ledger row.

## Agent spawn template

```text
You are PR<N> in the Open-FDD 4.0.11 audit patch train on github.com/bbartling/open-fdd.
Read docs/operations/patch_trains/4.0.11_audit_ledger.md (your issue rows) and docs/operations/GROK_CLOUD_4.0.11_AUDIT_HANDOFF.md (merge order + rules).
Implement only your slot; one PR; Fixes part of #…; no VERSION bump unless you are PR-R.
Watch gh pr checks and CodeRabbit until green on your head.
```
