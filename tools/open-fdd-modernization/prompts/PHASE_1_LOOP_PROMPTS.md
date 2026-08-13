# Phase 1 Loop-Engineered Prompts

These prompts are designed for fresh Codex/Cursor/agent sessions. Replace
bracketed values. Do not paste several execution prompts into one session unless
the prior PR is complete.

## Prompt 0 — Phase 1 orchestrator

```text
You are the primary implementation agent for Open-FDD Phase 1: React parity and
Python exit readiness.

Repository: [PATH OR REPO]
Target branch: [BRANCH]
Selected milestone/PR: [P1-M?-??]
User scenario/capability IDs: [IDS]

Before changing code:
1. Resolve repo root and read the complete applicable AGENTS.md hierarchy:
   root AGENTS.md, openfdd_agent_spec/AGENTS.md, tools/open-fdd-modernization/AGENTS.md.
2. Read tools/open-fdd-modernization/AGENT_SKILL_BRIDGE.md and load skills:
   - ALWAYS for UI work: openfdd_agent_spec/skills/openfdd-react-spa/SKILL.md
   - Plus any openfdd_agent_spec/skills/* matching SQL/cookbook/GHCR/ECM/ownership.
3. Read:
   - docs/migration/react-rust/README.md
   - PHASE_1_PREP_AND_REACT_PARITY.md
   - TEST_PARITY_AND_ACCEPTANCE.md
   - AGENT_EXECUTION_SYSTEM.md
   - DECISIONS.md, CAPABILITY_MATRIX.md, PYTHON_EXIT_MATRIX.md,
     API_CONTRACT_MATRIX.md, PARITY_EVIDENCE.md, SESSION_LOG.md
   - openfdd_agent_spec/BUILD_CHECKPOINTS.md (React/Rust section)
4. Inspect git status/branch/recent history. Preserve unrelated user changes.
5. Inspect code truth for the selected capability: React render path,
   session keys, Python call graph, current Rust routes/crates, SQL, storage,
   tests, scripts, images, docs, and consumers — following the openfdd-react-spa
   inventory workflow.
6. Restate the bounded objective, observable acceptance criteria, files likely
   in scope, risks, and tests. Split the work if it combines architecture, API,
   SQL, React, persistence, topology, cutover, or deletion beyond one coherent
   vertical slice.

Architecture law:
- React owns presentation, explicit browser state, routing, and chart assembly.
- Rust owns APIs, authorization, validation, jobs, persistence, orchestration,
  ingestion, artifacts, and error semantics.
- DataFusion SQL owns deterministic telemetry analytics and FDD.
- Python is a frozen characterization/oracle source only during Phase 1.
- Do not introduce FastAPI or another Python sidecar.
- Do not reproduce pandas logic in TypeScript.
- Do not silently fall back from SQL/DataFusion to pandas.
- Preserve BACnet/fieldbus/MQTTS safety and ownership.

Execute the loop:
OBSERVE -> INVENTORY -> CHARACTERIZE -> CONTRACT -> TEST FIRST -> IMPLEMENT ->
COMPARE -> HARDEN -> DOCUMENT -> PR-READY REVIEW.

Requirements:
- Define user-observable states including loading, empty, warning, failure,
  permission, stale revision, and retry/cancel where relevant.
- Add a versioned Rust-owned contract before coupling React.
- Generate/check TypeScript types and verify strict compilation.
- Use deterministic fixtures; compare raw semantics before formatting.
- Apply exact/numeric/temporal/interaction/visual/artifact/security/performance
  parity classes as relevant.
- Classify every mismatch. UNKNOWN blocks parity proof.
- Add observability and reversible flag behavior.
- Update all durable ledgers in the same change.
- Run the smallest relevant tests first, then affected suites, then production
  build/integration gates appropriate to risk.
- Report exact commands, pass/fail/skip counts, fixture hashes, and artifacts.

Do not stop at a plan or scaffold. Implement and verify the selected bounded PR.
Do not merge, deploy, delete old production code, or perform live BACnet writes
unless separately and explicitly authorized.

Final report:
1. outcome;
2. contract and ownership;
3. files changed;
4. tests/evidence;
5. parity result and mismatch classifications;
6. rollout/rollback;
7. Python exit impact;
8. remaining risks;
9. next bounded PR.
```

## Prompt 1 — Repository inventory and migration ledgers

```text
Perform P1-M0 inventory for Open-FDD. This is an evidence-producing audit, not
a speculative roadmap rewrite.

Read all repository instructions and modernization docs first. Inspect actual
code at the current commit. Build or update:
- CAPABILITY_MATRIX.md
- PYTHON_EXIT_MATRIX.md
- API_CONTRACT_MATRIX.md
- DECISIONS.md
- SESSION_LOG.md

Inventory all production Python entry points, including imports,
dynamic imports, CLI entry points, subprocesses, scripts, workflows,
Dockerfiles, compose, package extras, docs commands, tests, generated artifacts,
and runtime image references. Trace each user workflow from React SPA widgets
and session state through helpers, API/storage, computation, and downloads.

For every capability record:
- stable ID and user scenario;
- exact current code paths/functions/session keys;
- current inputs/outputs/errors/persistence;
- current Rust/DataFusion support;
- target React/Rust/SQL ownership;
- parity classes and fixtures;
- status and deletion blockers.

For every Python item record production consumers, oracle value, target owner,
replacement evidence required, and disposition as UNKNOWN until proven.

Pay special attention to jobs, package ingest, role mapping, rule tuning,
FDD/RCx plots, weather, analytics, metering, findings, reports, WattLab, and
authentication. Reconcile but do not blindly copy historical parity matrices.

Do not implement product features or delete code. Add automated inventory/policy
checks only if they are bounded and clearly support this PR.

Acceptance:
- 100% of discovered production Python entry points represented;
- no current React prohibition remains ambiguous after the proposed ADR scope;
- unknowns and conflicts listed explicitly;
- links and code references verified;
- exact searches/commands recorded.
```

## Prompt 2 — Characterization and oracle fixture

```text
Characterize capability [ID/SCENARIO] for later React/Rust replacement.

Read instructions and ledgers. Trace the full current React SPA/Python behavior.
Create the smallest legal deterministic fixture set covering happy, empty,
invalid, missing-role/data, permission, and boundary states relevant to the
capability.

Add only the Python instrumentation required to export normalized oracle JSON.
This code must not become a service or production dependency. Normalize key
order, unordered rows, timestamps/timezones, NaN/Inf/missing values, volatile
IDs/times, and artifact metadata. Stamp source commit, engine/registry versions,
fixture hashes, parameters, and mapping revision.

Capture the UI interaction manifest and controlled screenshots at the
defined viewports. Record widget labels/defaults/ranges/options, disabled rules,
session persistence, network calls, loading/errors, tables/charts/downloads,
keyboard path, and responsive behavior.

Prove repeatability with three exports. Do not refresh existing goldens without
explaining and reviewing every semantic difference.

Update CAPABILITY_MATRIX, PYTHON_EXIT_MATRIX, PARITY_EVIDENCE, and SESSION_LOG.
Report exact commands and artifacts. Do not build the replacement in this PR.
```

## Prompt 3 — Rust contract/API slice

```text
Implement the Rust-owned API contract for capability [ID] without React feature
implementation beyond a minimal client compile/contract probe.

Read instructions, current contracts, and reference evidence. Define:
- request/response/event/artifact schemas;
- auth roles;
- validation;
- error codes and retryability;
- timestamps/units/missing values;
- ordering/pagination/filtering;
- revision/idempotency;
- async progress/cancel/result semantics;
- compatibility/versioning.

Reuse services/central and existing Open-FDD contracts/crates where appropriate.
Use DataFusion SQL for deterministic tabular analytics. Never call Python,
pandas, or a Python subprocess. Do not expose server filesystem paths or
React SPA session structures.

Write failing Rust/domain/route/contract tests first. Add invalid, permission,
concurrency, and restart cases appropriate to the capability. Generate/check
the TypeScript client/types and compile them strictly. Add observability with
request/operation IDs.

Run fmt, clippy with warnings denied, affected tests, contract compatibility,
and TypeScript compile. Update API_CONTRACT_MATRIX, CAPABILITY_MATRIX,
PYTHON_EXIT_MATRIX, PARITY_EVIDENCE, and SESSION_LOG.

Do not redesign unrelated API families or implement the full React page.
```

## Prompt 4 — React parity slice

```text
Implement React capability [ID] against the approved Rust contract [CONTRACT].
The reference is the characterized React SPA scenario [EVIDENCE].

Read instructions and inspect both implementations. Match user-observable:
- route/tab/sidebar/page geometry;
- labels/help/defaults/options/ranges;
- control density and order;
- loading/progress/empty/warning/error/success;
- disabled rules;
- state persistence and URL/back/refresh behavior;
- metrics/tables/chart semantics/downloads;
- keyboard/focus/accessibility;
- desktop and narrow viewport.

Use local parity primitives and design tokens. Do not copy React SPA-generated
DOM/CSS blindly. Do not add engineering math, pandas logic, durable domain
state, filesystem knowledge, or a Python endpoint to React.

Add unit/component/browser/accessibility/visual tests. Use semantic chart
assertions plus controlled screenshots. Compare at identical fixture, viewport,
font, browser, device scale, theme, and server payload. Mask only documented
volatile regions. Classify every deviation and obtain explicit approval for an
intentional redesign.

Run lint, strict typecheck, unit/component, production build, affected Rust
integration, core browser scenario, accessibility scan, and visual comparison.
Update all ledgers and record feature flag/rollback behavior.
```

## Prompt 5 — DataFusion analytics/rule migration

```text
Migrate bounded analytics/rule family [FAMILY/IDS] from the Python reference to
DataFusion SQL with Rust orchestration and typed React-ready results.

First characterize current formula, required roles/units, equipment
applicability, parameters/defaults/bounds, occupancy/timezone/grid/confirmation,
missing data, statuses, and output identity. Add fixtures for thresholds,
streak boundaries, irregular sampling, duplicate timestamps, DST, missing role,
insufficient data, and representative normal/fault cases.

Implement SQL in the canonical registry. Rust validates and binds parameters,
authorizes, executes, shapes errors/results, and stamps provenance. Never use
unvalidated string interpolation or silent pandas fallback.

Compare normalized raw outputs to the independent oracle with per-field
absolute/relative tolerances and exact categorical identity. Report denominator,
max/p50/p95 deltas, skip/fail counts, and mismatch classifications. A registry
count or successful SQL parse is not parity.

Inspect query plan and representative performance. Add unit, SQL fixture, route,
contract, and consumer tests. Update registry parity metadata, cookbooks if
required, matrices, evidence, and session log.

Keep the PR bounded to this family. Do not delete the Python twin until its
caller has been cut over and the required observation window passes.
```

## Prompt 6 — Phase 1 qualification

```text
Qualify the Phase 1 React/Rust release candidate at commit [SHA].

Do not fix unrelated defects opportunistically. First verify all Phase 1 entry
criteria and enumerate exact images/config/fixtures.

Run and record:
- Rust fmt/clippy/workspace and targeted SQL registry/parity;
- React lint/strict types/unit/component/production build;
- contract compatibility and generated client;
- browser core workflows and responsive/keyboard/accessibility/visual;
- hostile upload and auth role matrix;
- performance/load/restart/recovery;
- production-like container stack with no Python UI/runtime;
- upgrade and tested React SPA routing rollback;
- source/image/SBOM scan for new-path Python dependencies.

Inspect artifacts and skipped tests. Classify every failure. Do not call the
phase complete with UNKNOWN mismatches, BLOCKED Python-exit rows, unexplained
skips, mutable image tags, or an untested rollback.

Publish a qualification record with commit, immutable digests, toolchains,
environment, fixture hashes, commands, denominators, tolerances, failures,
waivers/expiry, and approvals. Update ledgers and give a PASS, CONDITIONAL, or
FAIL verdict with exact reasons.
```
