# Agent Execution System

## Purpose

Provide a repeatable operating system for AI agents executing the Open-FDD
React/Rust modernization across many bounded PRs. This document supplements,
and never overrides, the nearest repository `AGENTS.md`.

## Bootstrap order for every new session

1. Resolve the repository root with `git rev-parse --show-toplevel`.
2. Read every applicable `AGENTS.md` from root to the files in scope.
3. Read the modernization `README.md`, current phase, test strategy, and this file.
4. Read the latest:
   - `DECISIONS.md`;
   - `CAPABILITY_MATRIX.md`;
   - `PYTHON_EXIT_MATRIX.md`;
   - `API_CONTRACT_MATRIX.md`;
   - `PARITY_EVIDENCE.md`;
   - `SESSION_LOG.md`;
   - relevant existing architecture/migration docs.
5. Inspect `git status`, current branch, recent commits, and open PR context.
6. Revalidate referenced code paths. Treat docs as claims until code confirms them.
7. Select exactly one bounded milestone/PR objective.

Never begin by rewriting architecture from memory.

## Authority and safety

Agents may make normal, reversible implementation changes inside the selected
PR. Stop for human direction when:

- product behavior is ambiguous and alternatives materially differ;
- deleting or relocating oracle/ECM history is proposed;
- auth/tenancy model changes;
- a persistent schema contraction is required;
- a live BACnet write or protocol behavior change is contemplated;
- credentials, secrets, protected branches, or private fixtures are required;
- unrelated dirty changes overlap the work;
- a waiver would lower an engineering correctness or security gate.

Always preserve:

- workspace data;
- BACnet UDP ownership and write safety;
- explicit DataFusion failure behavior;
- secret redaction;
- immutable evidence references;
- user changes outside the PR scope.

## The migration loop

Run this loop for each capability:

```text
OBSERVE
  -> INVENTORY
  -> CHARACTERIZE
  -> CONTRACT
  -> TEST FIRST
  -> IMPLEMENT
  -> COMPARE
  -> HARDEN
  -> DOCUMENT
  -> PR
  -> REVIEW
  -> CORRECT
  -> MERGE
  -> OBSERVE IN TARGET
  -> DELETE TWIN (later bounded PR)
```

### 1. OBSERVE

- execute the current workflow;
- capture inputs, visible states, network calls, outputs, errors, and timing;
- identify current user intent, not only widgets;
- record exact source commit and environment.

Output: scenario entry in capability matrix plus evidence locations.

### 2. INVENTORY

Trace:

- Streamlit render functions and session keys;
- Python helpers and imports;
- current API routes;
- Rust modules/crates;
- SQL rules/views;
- storage paths/schemas;
- Docker/compose/workflow/scripts;
- docs and tests;
- downstream artifact consumers.

Use `rg`/call sites. Do not infer ownership from filenames alone.

Output: dependency/ownership map and Python exit row.

### 3. CHARACTERIZE

Add deterministic fixtures and tests around user-observable behavior. Include
failure, empty, permission, and boundary states.

Output: reproducible reference artifact.

### 4. CONTRACT

Define the smallest stable request/response/event contract that supports the
scenario without exposing Python internals or filesystem layout.

Output: contract, examples, error codes, compatibility notes, generated/checked
TypeScript types.

### 5. TEST FIRST

Add or update tests that fail for the missing behavior at the appropriate
layers. Do not create brittle tests of implementation internals merely to claim
test-first work.

Output: meaningful failing test IDs recorded in PR notes.

### 6. IMPLEMENT

- Rust owns domain/API/persistence/orchestration;
- DataFusion SQL owns deterministic tabular computation;
- React owns UI/presentation/client state;
- Python is oracle-only during Phase 1 and absent from new runtime.

Output: smallest complete vertical slice.

### 7. COMPARE

Run normalized semantic, numeric, temporal, artifact, interaction, and visual
comparisons applicable to the slice. Classify every mismatch.

Output: parity evidence with denominator and tolerances.

### 8. HARDEN

Test auth, invalid inputs, concurrency, idempotency, cancellation, cleanup,
accessibility, large data, and production build/deploy.

Output: risk-specific tests and observability.

### 9. DOCUMENT

Update code docs and all ledgers in the same PR. Mark UNKNOWN/PARTIAL honestly.

Output: durable current state.

### 10. PR / REVIEW / CORRECT

Open a draft PR only after local relevant gates pass. Inspect all CI and review
feedback. Correct actionable defects within scope; reject suggestions that
violate the architecture with a concrete explanation.

### 11. MERGE / OBSERVE

After merge, verify the merged immutable artifact, not only the branch. Record
digest and target smoke. Do not refresh unrelated consumers unless scoped.

### 12. DELETE TWIN

Deletion is a separate PR after call-site proof and the required observation
window. Re-run regression and image/source scans.

## Bounded PR law

A good modernization PR has:

- one outcome stated as a user or platform capability;
- one primary contract change at most;
- a small set of directly related modules;
- tests and evidence;
- no opportunistic cleanup;
- documented rollout/rollback;
- matrix/log updates.

Split a PR if it combines two or more of:

- architectural authorization;
- API convention redesign;
- Rust service feature;
- SQL family migration;
- React page family;
- persistence schema change;
- container topology change;
- default-route cutover;
- deletion.

### PR description template

```markdown
## Objective

## User scenario / capability IDs

## Scope

## Out of scope

## Architecture ownership
- React:
- Rust:
- DataFusion SQL:
- Python reference:

## Contract changes
- version:
- compatibility:
- errors:

## Tests
- failing-before:
- unit:
- contract:
- integration:
- browser:
- parity:
- security/performance:

## Evidence
- source commit:
- fixture hashes:
- commands:
- comparison result:
- screenshots/artifacts:

## Rollout
- flag/cohort:
- observability:

## Rollback

## Python exit impact

## Documentation/ledgers updated

## Risks / known limits
```

## Durable ledgers

### Capability matrix

One row per user-observable capability. Status vocabulary:

- DISCOVERED;
- CHARACTERIZED;
- CONTRACTED;
- IMPLEMENTED;
- PARITY-PROVEN;
- CANARY;
- DEFAULT;
- DELETED-OLD;
- DEFERRED;
- BLOCKED.

Status may advance only with linked evidence.

### Python exit matrix

One row per Python module/entry point/runtime package:

```text
path
production consumers
behavior
target owner
oracle value
replacement PR
parity evidence
call-site scan
image/runtime references
disposition
deletion PR
```

### API contract matrix

One row per route/event/artifact:

```text
contract ID
method/path
auth roles
request schema
response schema
errors
idempotency/revision
operation semantics
React consumer
compatibility status
tests
```

### Parity evidence

Do not paste only screenshots. Record:

- capability/test ID;
- reference and candidate versions;
- fixture hashes;
- comparison classes;
- tolerances;
- pass/fail/skip denominator;
- mismatch classifications;
- reviewer;
- artifact location.

### Session log

Append after nontrivial work:

```text
date/session
objective
branch/commit/PR
code inspected
changes
tests/evidence
decisions
open risks
exact blocker/error
next bounded action
```

## Test selection by risk

| Change | Minimum tests |
| --- | --- |
| React styling only | component + accessibility + visual + production build |
| Widget/state | unit + component + keyboard + browser scenario |
| API schema | Rust route + contract compatibility + TypeScript compile + consumer |
| Job persistence | unit + integration + revision/idempotency + restart |
| SQL rule | fixture + parameter/boundary + parity + plan/performance |
| Upload/archive | property/fuzz + hostile cases + cleanup + integration |
| Artifact | generator unit + semantic parser + download/browser + safety |
| Auth | role matrix + negative cases + browser |
| Cutover flag | routing integration + sticky behavior + rollback drill |
| Deletion | call-site scan + full regression + image/SBOM + clean deploy |

## Verification discipline

Before claiming success:

1. run the test, do not merely name it;
2. read the full failure/output;
3. verify the command exercised changed code;
4. distinguish passed, skipped, xfailed, and not collected;
5. record environment and exact commit;
6. inspect generated artifacts/screenshots;
7. confirm production build/topology;
8. run a clean or isolated test where packaging/runtime is relevant.

Never say “all tests pass” when only an affected subset ran. State the exact set.

## Mismatch triage

For every parity failure, classify:

- REFERENCE_DEFECT;
- CANDIDATE_DEFECT;
- CONTRACT_AMBIGUITY;
- EXPECTED_ROUNDING;
- EXPECTED_REDESIGN;
- FIXTURE_GAP;
- ENVIRONMENT;
- NONDETERMINISM;
- UNKNOWN.

UNKNOWN blocks the capability from PARITY-PROVEN.

Do not widen a tolerance until the mismatch disappears. Explain the physical or
numerical basis and approve it.

## Recovery loop

When a test or implementation attempt fails:

1. preserve the exact command and output;
2. determine whether failure is code, fixture, environment, permission, or
   unrelated baseline;
3. minimize to the smallest reproduction;
4. inspect recent diffs and contract assumptions;
5. fix one cause;
6. rerun the narrow test;
7. rerun the affected suite;
8. update evidence/log;
9. do not stack speculative fixes.

After three attempts with the same external blocker:

- finish all non-blocked work;
- leave repository recoverable;
- record exact blocker, attempts, and next required human/external action;
- stop rather than inventing credentials, data, or behavior.

## Review roles

For high-risk PRs, seek distinct review perspectives:

- domain/correctness;
- Rust/DataFusion;
- React/UX/accessibility;
- security/operations;
- contract/backward compatibility.

One person may fill multiple roles, but the PR must show the perspectives were
considered.

## Agent prohibitions

- no new production Python/FastAPI sidecar;
- no pandas math in React;
- no browser filesystem coupling;
- no silent fallback;
- no broad deletes or `git reset --hard`;
- no live BACnet write without explicit approval;
- no secret/token output;
- no mass golden refresh;
- no moving-tag-only evidence;
- no “DONE” without linked tests and parity;
- no drive-by dependency upgrades;
- no giant cross-layer PR;
- no guessing unknown product behavior.

## Completion report

At the end of a PR/session, report:

- outcome first;
- files/contract changed;
- exact tests run and results;
- parity evidence;
- rollout/rollback status;
- Python exit matrix movement;
- remaining risks/blockers;
- next bounded PR.

Do not report effort, intentions, or generated file count as the outcome.
