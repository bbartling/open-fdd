# Agent execution system

## Goal

Provide a loop that lets one or more coding agents make sustained progress
without broad, unverifiable changes or false completion. The unit of execution
is a bounded PR from [MILESTONE_PR_MATRIX.md](MILESTONE_PR_MATRIX.md).

## Roles

One agent may perform several roles sequentially, but evidence identifies the
role. A phase closeout requires independent verification.

| Role | Responsibility |
|---|---|
| Scout | inventory code/contracts/tests/docs and reproduce baseline |
| Implementer | make the bounded change and focused tests |
| Oracle steward | maintain frozen Streamlit/pandas/Vibe 21 fixtures |
| Verifier | rerun gates from clean state and challenge claims |
| Security reviewer | evaluate trust boundaries and adversarial fixtures |
| Release operator | build/publish/boot/upgrade/rollback release artifacts |
| Human engineer/owner | approve product scope, engineering claims, waivers, activation, and BAS safety decisions |

## Required loop state

Maintain a small state file or issue comment with:

- program/phase/milestone/PR ID;
- base commit and branch;
- objective and non-goals;
- selected capability IDs;
- current verified facts and uncertainties;
- planned files and contracts;
- tests/evidence required;
- risks, external approvals, and blockers;
- status and next smallest action.

Do not use a giant mutable narrative as the only state.

## Execution loop

### 1. Orient

Read the required documents in order. Inspect repository status and nested
instructions. Confirm the requested PR is the earliest dependency-ready item.
Do not trust old completion prose; inspect code and evidence manifests.

### 2. Reproduce

Run the narrowest baseline that proves current behavior. Record versions,
fixtures, commands, and failure. For visual work run the current product and
reference at a fixed viewport. For model/rule work generate raw oracle outputs.

### 3. Bound

Write a mini-contract for this PR:

- observable user/API outcome;
- input/output/schema changes;
- owner of every calculation/state;
- compatibility and migration;
- exact files expected;
- tests and acceptance;
- rollback;
- explicit exclusions.

If the work cannot be verified independently within one PR, split it.

### 4. Characterize before replacement

Before rewriting Streamlit/Python/Vibe 21 behavior:

- capture representative, boundary, invalid, and branch cases;
- preserve raw values before rounding;
- freeze versions and hashes;
- record uncertainties as gaps, not guessed requirements.

### 5. Implement vertically

Prefer a thin, complete slice:

```text
contract -> backend behavior -> client behavior -> real integration test
-> evidence/docs -> capability status
```

Avoid broad directories of disconnected scaffolding. Never add a production
fallback to a demo/oracle merely to make the test green.

### 6. Test proportionally

Run focused tests during development, then all affected gates. Product UI work
requires a real-stack browser path. Computation replacements require
differential fixtures. Artifact handling requires adversarial security cases.
Release topology requires container and clean-host evidence.

### 7. Inspect the result as a user

Use the actual browser and generated artifact. Check console/network, keyboard,
loading/error/recovery, labels/provenance, and download contents. A component
test is not a substitute.

### 8. Adversarial self-review

Ask:

- Did I duplicate authority in React/Unity?
- Can invalid, stale, cross-site, corrupt, or oversized input pass?
- Does the code silently default or fall back?
- Did I call a screening/provisional result proven?
- Does a test mock the exact boundary it claims to verify?
- Can this be rolled back without data loss?
- Did docs/status get ahead of evidence?
- Did I introduce Python into a production path?

### 9. Prepare PR evidence

The PR description includes:

- why/what and capability IDs;
- contract/migration/security impact;
- commands and summarized results;
- screenshots/traces/artifact hashes;
- known limits and follow-ups;
- rollback;
- capability status transition requested.

### 10. Independent verification

Verifier uses a clean worktree/clone, reads the mini-contract, reruns acceptance,
checks evidence hashes, and attempts at least one failure/adversarial case. The
verifier may accept, request fixes, or reduce the claimed status.

### 11. Merge and update truth

After merge, update capability ledger/checkpoint with commit, PR, evidence, and
remaining limitations. Do not mark the phase complete unless every exit gate
has independent evidence.

## Worktree and concurrency rules

- One PR/branch per bounded mission.
- Avoid parallel changes to central route registries, shared schemas, design
  tokens, or generated clients without explicit ownership/sequence.
- Parallelize independent fixture generation, docs, or rule families only when
  their output contracts are frozen.
- Rebase/merge the dependency branch before final verification.
- Never use destructive Git operations on user changes.

## Stop and escalate conditions

Stop and request owner direction when:

- product/engineering claim or acceptable error threshold is undecided;
- a license prevents asset/model distribution;
- model portability cannot preserve qualified behavior;
- a schema change breaks approved clients without a migration path;
- an operation would expand into BAS control authority;
- required oracle data or real building evidence is unavailable;
- a secret/private dataset would need to enter the repository;
- the proposed PR crosses more than one phase dependency without approval.

Do not stop merely because work is difficult; continue with read-only analysis,
fixtures, or contract design while respecting the boundary.

## Completion language

Use precise language:

- “scaffolded” when only shape exists;
- “implemented” when focused tests pass;
- “verified” when real dependencies/user behavior pass;
- “qualified” only after release gates;
- “screening” or “candidate” when evidence is limited.

Never say “parity complete,” “Python removed,” “production ready,” or “turnkey”
without linking the corresponding evidence manifest.

