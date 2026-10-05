# Next-rev reboot checkpoint — 2026-10-05

**Pause reason:** operator reboot + meeting compile pause. Resume compiles only when operator says go.

## Tip baselines
- Soft-OPEN / Grok pin: `OPENFDD_IMAGE_TAG=sha-215e159` / platform **3.5.65** (`215e1594…`)
- Dirty primary checkout: `/home/ben/Desktop/open-fdd` at `4251505c` — **do not reset**
- Next closeout bump: **3.5.66** only at N9 (if still next)

## Orchestrator
- `.cursor/plans/next_rev_ghcr_refresh_train_20261005.plan.md` (N0–N9)
- Detail: `.cursor/plans/next_patch_security_rdf_sparql_memory_20261005.plan.md`
- Private audits: `/home/ben/Documents/Codex/private_audits/openfdd_20261005_215e159/`

## Open PRs (pushed; local verify incomplete — compile pause)
| PR | Branch | Scope |
| --- | --- | --- |
| #1144 | `tip/n1-security-s01-s02` | N1 S01/S02 vibe21 auth + session-id |
| #1145 | `tip/n2-evaluator-false-pass` | N2 Q02/Q04 gate26 + required-check |
| #1146 | `tip/n1-s06-login-throttle` | N1 S06 login XFF throttle |
| #1147 | `tip/n2-q01-gate36` | N2 Q01 gate36 |
| #1148 | `tip/n1-s04-edge-kit-scope` | N1 S04 edge-kit scope |

## Local worktrees (clean vs origin tip branches)
- `.worktrees/n1-security` → #1144
- `.worktrees/n2-evaluator` → #1145
- `.worktrees/n1-s06` → #1146
- `.worktrees/n2-q01` → #1147
- `.worktrees/n1-s04` → #1148

## Train status
- N0 intake: done
- N1/N2: in progress via open tips above; S03/S05/S07–S09 and Q03/Q05–Q07 remain
- N3–N9: not started; **no VERSION bump yet**
- Compiles: stopped for meetings; do not auto-resume after reboot

## After reboot
1. Do **not** `git reset` primary.
2. Say “resume compiles” to continue local verify → merge tips → rest of N1–N9.
3. `cargo clean` / wipe worktree `target/` after verify batches.
4. Cancel redundant Actions freely.
