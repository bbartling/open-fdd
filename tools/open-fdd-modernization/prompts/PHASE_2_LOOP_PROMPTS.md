# Phase 2 Loop-Engineered Prompts

Use only after Phase 1 exit evidence is approved. These prompts do not authorize
production deployment, destructive deletion, or live BACnet writes unless the
user separately grants that authority.

## Prompt 0 — Phase 2 orchestrator

```text
You are the primary implementation agent for Open-FDD Phase 2: React/Rust
cutover and production Python exit.

Repository: [PATH OR REPO]
Target branch: [BRANCH]
Selected milestone/PR: [P2-M?-??]
Environment/cohort if applicable: [VALUE]

Read the full applicable AGENTS.md hierarchy and all React/Rust modernization
docs and ledgers before acting. Inspect git state and current code truth.

Verify Phase 1 entry conditions:
- React/Rust/DataFusion stack operates without Python;
- capability, Python exit, API, parity, and decision ledgers are current;
- rollback and schema compatibility are tested;
- observability and cohort routing exist;
- no capability required by this PR is UNKNOWN/BLOCKED.

Architecture law:
- React is the UI.
- Rust owns APIs/domain/persistence/orchestration/artifacts.
- DataFusion SQL owns deterministic tabular analytics and FDD.
- No production Python or silent fallback.
- One durable job/data truth.
- Shadow comparisons never double-write production findings.
- BACnet remains fieldbus-owned; no live writes without explicit approval.

Select one bounded outcome. Do not combine a route flip, schema contraction,
computation migration, and deletion.

Execute:
OBSERVE -> VERIFY ENTRY -> TEST FAILURE/ROLLBACK -> IMPLEMENT -> COMPARE ->
HARDEN -> UPDATE LEDGERS -> PR-READY REVIEW.

Every result must include exact commit, immutable image digests when relevant,
commands, pass/fail/skip denominators, operational metrics, rollout/rollback,
and next bounded action. Do not stop at a plan. Do not merge/deploy/delete
without the authorization appropriate to this session.
```

## Prompt 1 — Cutover control plane

```text
Implement/verify P2-M0 cutover routing and observability.

Requirements:
- reversible React SPA/React cohort flag;
- sticky behavior through refresh/navigation;
- safe invalid/missing config default;
- audit trail for changes;
- no change to computation or storage semantics;
- schema backward-read or explicit fallback read-only policy;
- dashboards for UI errors, API latency/errors, operation status, DataFusion
  failures/skips, upload cleanup, job conflicts, fallback usage;
- no sensitive payload/token logging;
- alerts exercised with controlled failures.

Add route/config unit and integration tests, cohort browser tests, and a timed
rollback drill. Record recovery time, exact commands, configs, and evidence.
Update DECISIONS, API_CONTRACT_MATRIX, CAPABILITY_MATRIX, CUTOVER_LOG, and
SESSION_LOG.

Do not flip the production default in this PR.
```

## Prompt 2 — Computation closure

```text
Close production Python computation family [FAMILY] using the prescribed
contract -> SQL/Rust -> parity -> caller cutover loop.

Inspect every Python consumer, not only the implementation file. Characterize
roles/units/parameters/time/grid/missing/error/status semantics. Add boundary
fixtures and failing tests. Implement deterministic table math in DataFusion
SQL and remaining orchestration/IO in Rust.

Compare raw normalized results to the oracle:
- exact IDs/statuses/applicability/errors;
- per-metric numeric tolerances with rationale;
- temporal boundary coverage;
- denominator and mismatch distribution;
- no ignored/skipped UNKNOWN.

Cut the production caller to Rust/DataFusion behind its flag. Add tracing or a
policy test proving no python/pandas/subprocess invocation. Keep the old code
present but unreachable until the deletion window.

Run Rust, SQL, contract, React consumer, integration, performance, and
production-like no-Python tests. Update registry metadata, cookbooks/ledgers,
and record the future deletion PR.
```

## Prompt 3 — Shadow comparison and soak

```text
Run or implement the bounded shadow/soak qualification for [CAPABILITIES/SITES].

Safety:
- use authorized immutable input/config snapshots;
- do not write shadow results into production findings;
- cap CPU/memory/storage and comparison retention;
- redact sensitive values;
- never invoke pandas inline as a fallback to a user request.

Exercise normal, large, concurrent, restart, cancellation, expired-auth, stale
revision, artifact retention, partial dependency outage, timezone, and browser
refresh scenarios as applicable.

For comparisons, record reference/candidate versions, fixtures/input hashes,
parameters/mapping revisions, exact/numeric/temporal/artifact results,
denominators, percentiles/max deltas, and mismatch classification. UNKNOWN or a
critical candidate defect fails the gate.

Compare success/error/latency/resource metrics to approved budgets. Create
regression tests for release-blocking defects. Update PARITY_EVIDENCE,
CUTOVER_LOG, capability status, and session log. Provide PASS/FAIL and the exact
next canary prerequisite.
```

## Prompt 4 — Canary promotion decision

```text
Evaluate promotion from canary stage [CURRENT] to [NEXT] for React at immutable
release [SHA/DIGESTS].

This is an evidence-based release decision. Read cutover gates and current
incident/fallback logs. Gather:
- session/workflow sample counts;
- core operation success;
- UI/API/DataFusion errors and latency;
- parity defects;
- accessibility/security issues;
- fallback usage and reason codes;
- data integrity and orphan/retention health;
- support feedback;
- backup/rollback readiness.

Check all promotion thresholds and minimum observation duration/usage. Do not
average away a correctness, security, or data-integrity defect. If any red-line
trigger is present, recommend rollback and produce the bounded recovery steps.

Output a signed-style decision record:
PROMOTE, HOLD, or ROLLBACK; evidence window; exact release; thresholds versus
actuals; incidents; open risks; approvals required; next review trigger.

Do not change production routing unless explicitly authorized.
```

## Prompt 5 — Default React route flip

```text
Prepare and, only if explicitly authorized, implement the P2-M4 React-default
route flip.

Verify:
- approved 100% canary evidence;
- no P0/P1 defect;
- schema/fallback compatibility;
- immutable release digests;
- tested rollback;
- operator/support docs;
- fallback reason telemetry;
- deep-link redirects;
- monitoring and on-call owner.

The change must alter routing/config only. Do not combine feature work, contract
breaks, schema contraction, or deletions.

Add/update routing tests and execute pre/post smoke plus rollback rehearsal.
Record exact time, config, release, metrics, and observation window in
CUTOVER_LOG. Keep React SPA frozen and explicitly labeled during the window.
```

## Prompt 6 — Python twin deletion

```text
Delete the bounded Python/React SPA twin set [PATHS] only after verifying all
deletion gates.

Before deletion:
1. Read repository safety/instructions and the approved disposition rows.
2. Confirm replacement PRs, parity evidence, caller cutover, and observation
   window.
3. Search all imports, dynamic imports, subprocesses, entry points, scripts,
   workflows, Docker/compose, docs, tests, package extras, image references, and
   artifact consumers.
4. Confirm rollback uses an immutable old release rather than active twin code.
5. Record exact paths and recoverability.

Delete only the declared paths and directly obsolete wiring. Preserve
oracle/ECM/history unless the human decision explicitly includes them. Do not
use broad destructive commands. Update tests, dependencies, containers,
workflows, and docs only within this deletion slice.

Required verification:
- relevant full regression;
- production React/Rust build;
- fresh no-Python deployment;
- upgrade from last supported release;
- source scan for call sites/banned dependencies;
- production image and SBOM scan;
- browser/API smoke;
- backup/restore or artifact compatibility where relevant.

Update PYTHON_EXIT_MATRIX to DELETED with evidence, CAPABILITY_MATRIX,
CUTOVER_LOG, and SESSION_LOG. Report precisely what was removed and the immutable
recovery reference.
```

## Prompt 7 — React product removal

```text
Execute the approved React product removal PR after leaf Python twins have
already been deleted and the fallback window is closed.

Scope candidates must be enumerated explicitly and call-site verified:
- React SPA entry point and migrated UI modules;
- React-only tests and smoke scripts;
- UI Python dependency manifests;
- web container/image/compose wiring;
- obsolete environment variables and docs;
- stale current-state instructions.

Do not delete oracle/reference tooling or root Python packages by association.
Relocate approved oracle-only tools so they cannot be built into production.

Run clean source scans, Rust/React/full browser/contract/container gates, image
filesystem and SBOM scans, fresh deploy, and upgrade test. Verify no docs,
workflows, or release recipes tell operators to run product UI.

Record the last immutable React SPA release/digests and recovery procedure.
```

## Prompt 8 — Final no-Python qualification

```text
Qualify Open-FDD Phase 2 at commit [SHA] as a production no-Python release.

Use immutable images and a clean host/environment with no Python installation
available to product services. Verify fresh install and upgrade from the last
React SPA release.

Run:
- Rust fmt/clippy/workspace/integration;
- DataFusion registry/rule fixtures/parity/performance;
- React lint/type/unit/component/build;
- API contract compatibility;
- browser core, responsive, keyboard, accessibility, visual;
- auth/security/hostile upload;
- performance/concurrency/restart/retention;
- backup/restore;
- source, workflow, compose, image filesystem, package inventory, and SBOM scans
  for Python/pandas;
- documentation/link/quick-start checks.

Inspect skips and artifacts. Produce a final capability matrix, Python exit
matrix, contract statement, cutover history, incidents/corrections, exact
digests, last React SPA recovery reference, accepted risk, and Phase 3 readiness.

PASS only if React is the sole production UI, all production behavior is
Rust/DataFusion-owned, no runtime Python exists, current docs match topology,
and clean fresh/upgrade deployments pass. Otherwise return FAIL with exact
blocking rows and commands.
```

## Prompt 9 — Reviewer

```text
Review PR [NUMBER/BRANCH] against the Open-FDD modernization architecture and
its declared bounded scope.

Read all instructions, phase docs, ledgers, PR description, diff, tests, and CI.
Review for:
- behavioral/correctness regressions;
- ownership violations (math in React, Python runtime, non-SQL deterministic
  analytics, browser filesystem coupling);
- contract compatibility/error/auth/idempotency/revision issues;
- missing time/unit/grid/missing-data behavior;
- parity evidence quality and denominators;
- accessibility/interaction/visual gaps;
- upload/security/tenant isolation;
- performance/resource/recovery;
- unsafe BACnet/MQTT changes;
- deletion without proof;
- incomplete ledgers/docs;
- unrelated scope.

Prioritize concrete defects with exact file/line and failure scenario. Do not
request cosmetic churn or a broader refactor unless required for correctness.
Distinguish blocking, follow-up, and optional feedback. Verify tests actually
exercise changed behavior and note skipped/absent gates.
```

## Prompt 10 — Failure recovery

```text
Recover bounded task [TASK] from failure [EXACT TEST/ERROR].

Do not stack speculative edits. Preserve the exact command/output and current
git state. Classify failure as code, fixture, contract ambiguity, environment,
permission/credential, unrelated baseline, or unknown.

Minimize the reproduction. Inspect relevant diff, contract, fixture hashes,
toolchain, generated files, service logs, and last known-good evidence. Form one
testable hypothesis, make the smallest correction, run the narrow test, then
the affected suite and production-relevant gate.

If the same external blocker persists for three attempts, finish non-blocked
work, leave the repo recoverable, record attempts and exact required external
action in SESSION_LOG, and stop. Never invent secrets, private data, expected
outputs, tolerances, or product behavior.
```
