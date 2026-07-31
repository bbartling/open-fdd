# Phase 2 — React/Rust Cutover and Production Python Exit

## Objective

Make React + Rust + DataFusion the default and then sole production product.
Phase 2 is an operational migration with deletion as its final consequence. It
is not permission to add missing parity work; unresolved functional blockers
return to Phase 1.

## Entry conditions

Do not begin cutover until:

- Phase 1 exit evidence is approved;
- the React/Rust stack runs without a Python container or interpreter;
- every user capability has an owner and test;
- persisted jobs/configs/mappings/artifacts have compatibility coverage;
- cutover flags work at deployment, tenant/site, and user cohort scope as
  appropriate;
- rollback has been rehearsed;
- dashboards and alerts exist for both product and migration health;
- the deletion list is call-site verified.

## Cutover principles

1. **One source of durable truth.** Both UIs may temporarily read the same Rust
   job/data APIs; they must not create divergent stores.
2. **One source of computation truth.** Production FDD and deterministic
   analytics run once in DataFusion. “Dual run” means comparison jobs, not two
   competing writes to production findings.
3. **Shadow before canary, canary before default, default before deletion.**
4. **Rollback changes routing, not data interpretation.** Schema evolution must
   remain backward readable during the rollback window.
5. **Delete from leaves inward.** Remove unused Python feature modules before
   removing the Streamlit entry point, packaging, and base image.
6. **No silent fallback.** A Rust/DataFusion failure is observable and handled
   according to its contract; it never invokes pandas.

---

## Milestone P2-M0 — Release control plane and migration observability

### Goal

Make cutover measurable and reversible.

### PR P2-M0-01 — Feature flag and cohort routing

Implement and test:

- `ui_generation=streamlit|react` or equivalent;
- site/tenant cohort rules if multi-site operation requires them;
- a user-accessible fallback link during approved stages;
- sticky routing so refreshes do not bounce between UIs;
- flag audit log;
- safe default when config is absent or invalid;
- emergency rollback that does not require rebuilding images.

The flag must not alter API semantics or computation engines.

### PR P2-M0-02 — Migration telemetry

Instrument:

- route/page views;
- API latency/error by route and UI generation;
- operation duration, cancellation, retry, and failure stage;
- upload validation failure categories;
- DataFusion query/rule duration and skip/failure counts;
- React error-boundary events;
- artifact generation/download failures;
- authentication/authorization failures;
- comparison deltas for controlled shadow runs;
- job revision conflicts;
- fallback clicks and reason code.

Exclude secrets, raw credentials, and sensitive telemetry values from logs.

Define service-level indicators and alerts:

| Indicator | Suggested initial gate |
| --- | --- |
| React uncaught error sessions | < 0.5% |
| Core operation success | not worse than Streamlit baseline by > 1 percentage point |
| API p95 | within approved per-route budget |
| DataFusion rule failure | no unexplained increase |
| Upload orphan cleanup | 100% within retention target |
| Authorization regression | zero known privilege escalation |

Thresholds are starting points; owners must approve actual release values.

### PR P2-M0-03 — Data/schema rollback compatibility

Prove:

- new job/config writes remain readable by the fallback during the rollback
  window, or fallback is explicitly read-only for newly written versions;
- schema migrations are expand/contract, not destructive in the same release;
- artifacts are content-addressed/versioned where appropriate;
- optimistic-concurrency revisions survive both UIs;
- backup/restore test covers migration state.

### Milestone gate

- switching a cohort requires configuration only;
- rollback drill completes inside the approved recovery-time objective;
- dashboards and alerts are reviewed with forced failures.

---

## Milestone P2-M1 — DataFusion and Rust computation closure

### Goal

Remove every production computation reason to invoke Python.

### PR sequence per rule/analytics family

Use a bounded family, not the entire registry:

1. **Contract/metadata PR**
   - canonical ID, aliases, equipment applicability;
   - required roles and units;
   - parameters/defaults/bounds;
   - output schema/statuses;
   - parity status and fixtures.
2. **SQL implementation PR**
   - DataFusion-compatible SQL;
   - explicit interval, confirmation, occupancy, missing-data, and timezone
     behavior;
   - query plan/performance evidence;
   - no string interpolation for unvalidated user data.
3. **Parity PR**
   - normalized oracle results;
   - exact categorical comparison;
   - numeric tolerance rationale;
   - mismatch classification;
   - approved exceptions recorded at row level.
4. **Caller cutover PR**
   - Rust route/service uses canonical SQL path;
   - React receives typed result;
   - Python caller becomes unreachable from production.
5. **Twin deletion PR**
   - delete only after observation window and call-site proof.

### Required behavior decisions

Every migrated computation explicitly handles:

- sampling interval and irregular grids;
- streak/confirmation windows;
- occupancy boundaries and holidays;
- timezone and DST;
- missing roles versus missing samples;
- duplicate timestamps;
- unit normalization;
- equipment applicability;
- insufficient-data status;
- partial rule failure;
- deterministic ordering;
- version/provenance stamping.

### Rule registry closure

The current code distinguishes a SQL registry count from the pandas cookbook
count. Phase 2 must not claim parity from counts. Each registry row needs:

```text
rule_id
sql_path
version/hash
parity_status
oracle_reference
required_roles
parameters
equipment_types
known_limitations
fixture coverage
last_proven_commit
```

Allowed production statuses should be deliberately defined, for example:

- PROVEN;
- PROVISIONAL with visible limitation;
- DISABLED;
- CUSTOM/UNSUPPORTED.

“Ported” is not equivalent to PROVEN.

### Rust replacement families

Audit and replace non-SQL Python behavior:

- ZIP/package parsing and validation;
- CSV inventory and role mapping;
- weather acquisition/provenance if part of product runtime;
- job/session/config persistence;
- result cache and artifact manifest;
- findings/dispositions;
- export packaging;
- workbook/DOCX/PDF generation if required;
- units and formatting that affect contracts;
- CLI and administrative scripts required by production;
- cleanup/retention tasks.

Choose maintained Rust crates deliberately. For each dependency record license,
security posture, maintenance, supported format subset, and fallback behavior.

### Tests and targets

- unit/property tests for parameters and time-window boundaries;
- SQL fixture tests for each rule status;
- Rust integration tests through public APIs;
- oracle comparisons with documented tolerances;
- mutation spot-checks for high-risk formulas;
- query plan regression checks for representative sizes;
- concurrency/cancellation tests;
- zero production invocation of `python`, `pip`, `streamlit`, `pandas`, or
  Python entry points in runtime tracing and repository policy scans.

### Milestone gate

- all in-scope production computations are SQL or Rust;
- every exception is an explicit non-production oracle or approved product
  defer;
- new-stack qualification succeeds on a host without Python installed.

---

## Milestone P2-M2 — Shadow and controlled dual-run

### Goal

Observe the new product under real workflows without creating conflicting
production writes.

### PR P2-M2-01 — Shadow comparison harness

For authorized representative jobs:

- replay immutable input/config snapshots;
- run canonical Rust/DataFusion computation;
- compare with versioned Phase 1 oracle output or the old UI’s normalized API
  results;
- write comparison artifacts outside production findings;
- redact/aggregate telemetry appropriately;
- cap resource usage and schedule;
- classify delta as expected rounding, ordering, timestamp/grid, mapping,
  parameter, formula, missing data, or defect.

Do not execute a pandas fallback inline with a user’s production request.

### PR P2-M2-02 — Soak qualification

Exercise:

- repeated runs;
- concurrent jobs;
- large uploads;
- restart mid-operation;
- central and web rolling restart;
- expired auth;
- stale revisions;
- artifact retention;
- partial fieldbus/MQTT outage without changing protocol behavior;
- clock/timezone boundaries;
- browser refresh/back/forward.

### Exit criteria

- no unexplained semantic delta in critical outputs;
- error and latency budgets pass for the agreed duration;
- no data corruption or orphan growth;
- all release-blocking defects have regression tests.

---

## Milestone P2-M3 — Canary cohorts

### Goal

Serve React as the primary UI to a small, observable group.

### Canary stages

Suggested sequence:

1. maintainers/internal synthetic jobs;
2. internal real read-only inspection;
3. internal full workflows;
4. selected site/operators;
5. 10% eligible sessions;
6. 25%;
7. 50%;
8. 100% with Streamlit fallback still available.

Each promotion is a recorded decision, not an automatic elapsed-time step.

### Promotion checklist

- minimum sample/session count met;
- core workflow success at/above gate;
- no critical security/accessibility issue;
- error budget healthy;
- no unresolved result parity defect;
- support/fallback feedback reviewed;
- backup and rollback still valid;
- exact image digests recorded.

### Rollback triggers

Immediate rollback examples:

- incorrect FDD/findings with potential engineering impact;
- job/config corruption;
- authorization bypass;
- widespread inability to upload/run/download;
- error rate or latency beyond approved red line;
- irrecoverable browser state loop.

After rollback:

1. freeze cohort expansion;
2. preserve logs/evidence;
3. open a bounded defect PR;
4. add regression test;
5. rerun shadow/soak;
6. repeat the failed canary stage.

Do not “fix forward” through a high-impact correctness or data-integrity defect
without an explicit incident decision.

---

## Milestone P2-M4 — Default React and fallback observation window

### Goal

Make React the default for all users while retaining an explicit, measured
Streamlit fallback for a fixed period.

### PR P2-M4-01 — Default route flip

- change default route/config;
- update operator docs and screenshots;
- preserve deep-link redirects;
- make Streamlit fallback clearly labeled and instrumented;
- show a feedback/reason path;
- keep central computation and storage unchanged.

### Observation window

Set an explicit period or usage threshold, such as:

- two release cycles; and
- a minimum number of successful core workflow executions; and
- at least one operational restart/upgrade event.

During the window:

- no new Streamlit features;
- only critical reference fixes;
- every fallback use receives a reason code;
- deletion PRs may be prepared but not merged;
- job/schema compatibility remains in force.

### Milestone gate

- fallback usage is zero or explained/accepted;
- no unresolved P0/P1 issue;
- success, performance, and correctness gates remain healthy;
- deletion is approved.

---

## Milestone P2-M5 — Production Python and Streamlit deletion

### Goal

Remove inactive twins, dependencies, images, workflows, and documentation in
small recoverable PRs.

### Deletion order

#### PR P2-M5-01 — Leaf Python feature modules

Delete verified-unused:

- old UI-only analytics callers;
- pandas production fallbacks;
- Python job/session adapters;
- Python package/report workers replaced by Rust;
- obsolete caches and bridges.

For each deleted path include:

- replacement;
- last active call-site evidence;
- parity/test evidence;
- `rg`/dependency scan;
- rollback reference.

#### PR P2-M5-02 — Streamlit application and UI package

Remove:

- `services/ui/streamlit_app.py`;
- migrated `services/ui/app/` production modules;
- Streamlit UI tests/scripts;
- `services/ui/pyproject.toml` and requirements;
- obsolete Streamlit specs;
- Streamlit container build.

If oracle fixtures/tools stay, relocate them to a name and build target that
cannot be confused with the product UI.

#### PR P2-M5-03 — Root Python runtime/package decision

Apply the approved decision to `open_fdd/`:

- archive/separate oracle-only Python, or retain it as non-production with
  strong packaging boundaries, or delete it;
- remove production compose/image/install references;
- remove CLI entry points replaced by Rust;
- update versioning and consumer docs.

This PR must not accidentally delete valued ECM/oracle history without the
human decision required by the program charter.

#### PR P2-M5-04 — CI, release, compose, and docs cleanup

Remove or update:

- Python/Streamlit workflows;
- pytest gates that only cover deleted production code;
- Python build/publish steps no longer in product scope;
- `openfdd-ui` image references if replaced by web/central delivery;
- compose services and environment variables;
- release smoke scripts;
- architecture diagrams, web-app docs, quick starts, ports, screenshots;
- stale “current Streamlit” statements.

Preserve historical migration docs with a clear historical banner when useful.

### Deletion safety gates

- clean repository search for banned production dependencies;
- clean production image filesystem/package inventory;
- SBOM contains no Python/Streamlit/pandas package;
- fresh-host deployment succeeds without Python;
- upgrade from last Streamlit release succeeds;
- browser and API qualification passes;
- artifact/schema backward-read promises are met;
- backup restore works.

### Recovery

Deletion is recovered through a tagged immutable old release, not by leaving
dead code paths wired into the new release. Record the last known-good commit
and image digests.

---

## Milestone P2-M6 — Final qualification and closeout

### Required qualification matrix

| Area | Evidence |
| --- | --- |
| Rust | fmt, clippy `-D warnings`, workspace unit/integration tests |
| DataFusion | registry integrity, per-rule fixtures, parity, plans/performance |
| React | lint, strict types, unit/component, production build |
| Contracts | compatibility and generated client verification |
| Browser | core scenarios, responsive, keyboard, accessibility, visual/semantic |
| Security | auth matrix, hostile upload, dependency/container scan, CSP/CORS |
| Operations | immutable-image deploy, health, restart, backup/restore, rollback record |
| Performance | upload/query/chart budgets and soak |
| Removal | source, image, SBOM, workflow, compose, and docs scans |

### Closeout artifacts

- final capability matrix;
- final Python exit matrix;
- API compatibility/version statement;
- cutover timeline and cohort decisions;
- incidents and corrective PRs;
- immutable image SHAs/digests;
- last Streamlit release reference;
- accepted residual risks;
- Phase 3 prerequisites that are actually met.

## Phase 2 exit criteria

Phase 2 is DONE only when:

- React is the sole production UI;
- Rust owns application APIs and durable behavior;
- DataFusion SQL owns deterministic FDD/analytics;
- production runtime and images require no Python;
- Streamlit and Python production twins are deleted;
- all current docs and operations refer to the new topology;
- a fresh deployment and upgrade deployment both pass;
- rollback history is preserved without maintaining two active products.

## Phase 2 anti-patterns

- deleting Python at the start of cutover;
- writing production findings from both engines;
- using visual parity as proof of calculation parity;
- keeping Streamlit “just in case” with no removal date;
- declaring success because React returns HTTP 200;
- merging schema contraction with default-route flip;
- deleting workflows before equivalent gates exist;
- retaining Python through an undocumented shell subprocess;
- treating a public container tag as immutable evidence.
