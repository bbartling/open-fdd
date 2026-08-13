# Open-FDD React/Rust Modernization Program

Status: proposed execution plan  
Repository inspected: `bbartling/open-fdd` at `d56ec14b0f3f92846d664034f50d12803a45ce6e`  
Planning date: 2026-07-30

## Mission

Replace the Open-FDD React product UI with a React application while moving
production application behavior out of Python. Deterministic analytics and FDD
belong in DataFusion SQL. Ingestion, orchestration, durable jobs, validation,
exports, protocol handling, and APIs belong in Rust. React owns presentation,
interaction state, routing, and browser-side behavior.

This is not a big-bang rewrite. It is a contract-first strangler migration:

1. freeze the current React SPA behavior as an executable reference;
2. expose stable Rust-owned contracts;
3. reproduce the React UX in React one vertical slice at a time;
4. dual-run new and old computation paths where independent comparison is useful;
5. cut traffic over behind reversible flags;
6. delete production Python only after proof and a rollback window.

## Required end state

```text
Browser
  -> React SPA
      -> central Rust API
          -> jobs / configs / mappings / artifacts
          -> DataFusion SQL analytics and FDD
          -> Arrow / Feather / Parquet historian
          -> fieldbus and edge status

Fieldbus Rust
  -> BACnet / Modbus / Haystack
  -> MQTTS
  -> central Rust ingest

Python
  -> absent from production images and runtime paths
  -> optionally retained outside production as a versioned test oracle/archive
     until a separate product decision removes it
```

The phrase “remove Python” means no Python interpreter, React SPA server,
pandas fallback, Python job store, Python report worker, or Python computation
path is required to operate the product. Deleting the historical oracle source
is a separate decision; keeping a non-shipping oracle does not violate the
runtime goal.

## Existing code truth that this plan builds on

| Concern | Current Open-FDD source | Modernization direction |
| --- | --- | --- |
| Product UI | `frontend/web`, `frontend/web` | React SPA, initially behavior-compatible |
| Product FDD | `sql_rules/`, `crates/fdd_rules`, `POST /api/fdd/run` | Keep and expand; never move math into React |
| Data execution | `crates/fdd_sql`, DataFusion 43 | Canonical deterministic analytics engine |
| Central API | `services/central/` | Primary browser API and durable state owner |
| Jobs | `services/central/src/jobs.rs`; Python client in `frontend/web` | Rust remains source of truth; React consumes it |
| CSV/package ingest | UI package helpers plus edge/central routes | Rust endpoint and asynchronous job |
| Oracle/legacy analytics | `open_fdd.rules`, `open_fdd.analytics`, `open_fdd.reporting`, UI cookbook | Frozen comparison source during migration |
| Edge/protocols | `edge/`, `services/fieldbus/`, `openfdd_mqtt` | Phase 3 live-data extension |
| BACnet ownership | fieldbus owns UDP 47808 and publishes MQTTS | Preserve exactly; React never touches BACnet wire |

Several checked-in statements currently prohibit React (`frontend/README.md`,
`frontend/web`, architecture and web-app docs). Those are current-state
locks, not files to ignore. Phase 1 Milestone 0 must replace them in one
architecture-decision PR before React implementation begins.

## Program phases

| Phase | Purpose | Production result |
| --- | --- | --- |
| Phase 1 | Prepare the replacement: contracts, parity evidence, Rust seams, React implementation, Python freeze | React is complete behind a flag; old UI remains default; no new production Python |
| Phase 2 | Cut over and remove production Python | React/Rust/DataFusion becomes default and only production path after rollback window |
| Phase 3 | Add live edge workflows beyond CSV | BACnet/other protocols flow through fieldbus and MQTTS into job-aware live React views |

Phase 3 is deliberately an outlook, not authorization to change live BACnet or
MQTT behavior during Phases 1 or 2.

## Document map

| Document | Use |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Open-FDD React SPA→React agent law (Rust/central; no FastAPI) |
| [AGENT_SKILL_BRIDGE.md](AGENT_SKILL_BRIDGE.md) | Bridges `openfdd_agent_spec` skills ↔ this kit + openfdd-react-spa |
| [openfdd_agent_spec/skills/openfdd-react-spa/SKILL.md | **Required** skill for every UI parity/port PR |
| [PHASE_1_PREP_AND_REACT_PARITY.md](PHASE_1_PREP_AND_REACT_PARITY.md) | Detailed Phase 1 milestones, PRs, tests, and exit gate |
| [PHASE_2_CUTOVER_AND_PYTHON_EXIT.md](PHASE_2_CUTOVER_AND_PYTHON_EXIT.md) | Detailed Phase 2 cutover, deletion, rollback, and qualification |
| [PHASE_3_EDGE_STREAMING_OUTLOOK.md](PHASE_3_EDGE_STREAMING_OUTLOOK.md) | Later BACnet/MQTTS/live-data architecture and prerequisites |
| [MILESTONE_PR_MATRIX.md](MILESTONE_PR_MATRIX.md) | Sequenced PR map, dependencies, deliverables, and promotion gates |
| [OPENFDD_CODEBASE_MAP.md](OPENFDD_CODEBASE_MAP.md) | Current source-to-target ownership map and required audit paths |
| [TEST_PARITY_AND_ACCEPTANCE.md](TEST_PARITY_AND_ACCEPTANCE.md) | Cross-phase test pyramid, evidence, tolerances, and browser parity protocol |
| [AGENT_EXECUTION_SYSTEM.md](AGENT_EXECUTION_SYSTEM.md) | Rules for autonomous agents, bounded PR protocol, state files, and stop conditions |
| [prompts/PHASE_1_LOOP_PROMPTS.md](prompts/PHASE_1_LOOP_PROMPTS.md) | Ready-to-paste Phase 1 execution prompts |
| [prompts/PHASE_2_LOOP_PROMPTS.md](prompts/PHASE_2_LOOP_PROMPTS.md) | Ready-to-paste Phase 2 execution, review, recovery, and deletion prompts |
| [`openfdd_agent_spec/`](../../openfdd_agent_spec/) | Product agent OS, PR protocol, Milestone skills, BUILD_CHECKPOINTS |

## Non-negotiable architecture

### React is not a new backend

React may format values, manage form state, render charts, and provide optimistic
interaction. It must not reproduce FDD, rollups, unit conversions that affect
engineering meaning, report calculations, or durable job rules.

### Rust contracts precede React screens

Every screen slice starts with:

```text
user behavior
  -> versioned request/response/event contract
  -> Rust implementation and contract tests
  -> generated or checked TypeScript client
  -> React state and presentation
```

Do not make the SPA scrape React SPA output, call Python-only endpoints, or
depend on Python filesystem layouts.

### DataFusion SQL is the computation boundary

If an operation is deterministic over tabular telemetry and can reasonably be
expressed in DataFusion SQL, implement it there. Rust owns query registration,
typed parameters, validation, authorization, execution, result shaping, and
error translation.

### Python is frozen during Phase 1

Allowed Phase 1 Python changes:

- characterization tests;
- deterministic fixture/oracle export;
- instrumentation needed to observe current behavior;
- critical bug fixes applied to both reference expectations and the new path.

Disallowed Phase 1 Python changes:

- new product features;
- new canonical rules or analytics;
- new Python services or FastAPI sidecars;
- new persistence formats that React must later consume;
- a silent pandas fallback for DataFusion failures.

### Deletion follows proof

No Python or React SPA module is deleted because a similar React component
exists. Deletion requires:

1. ownership assigned to React, Rust, or DataFusion SQL;
2. replacement shipped behind a flag;
3. characterization/parity evidence;
4. production-like smoke evidence;
5. rollback plan;
6. dependency and call-site search showing no active consumer;
7. explicit deletion PR after the observation window.

## Program-level gates

### Phase 1 entry

- modernization ADR approved;
- repository instructions updated so React work is allowed;
- an inventory owner is named;
- representative fixtures are legally and operationally available;
- CI can build Rust and Node projects.

### Phase 1 exit

- all in-scope React SPA workflows exist in React behind a feature flag;
- React talks only to Rust-owned/versioned APIs;
- core CSV-to-findings flow runs without Python;
- all deterministic production analytics and FDD used by that flow execute in
  DataFusion SQL;
- Python is frozen and absent from the new UI runtime;
- parity, accessibility, security, performance, and rollback gates pass;
- every Python production module has a KEEP-AS-ORACLE, REPLACE, or DELETE record.

### Phase 2 exit

- React is the default UI and has completed the defined soak period;
- production images and compose recipes contain no Python/React SPA dependency;
- no production route invokes pandas or a Python subprocess;
- React SPA/Python runtime code, CI jobs, requirements, images, and docs have
  been removed or moved to a clearly non-shipping oracle archive;
- rollback no longer depends on silently maintaining two product implementations;
- release evidence is reproducible from immutable image SHAs/digests.

## Decisions that require a human product call

Agents must surface, not silently decide:

- whether the pandas oracle remains in the main repository, a separate archive,
  or is deleted after Phase 2;
- whether historical static HTML/report formats must remain byte-compatible or
  only semantically compatible;
- which React SPA behaviors are intentional product requirements versus demo
  artifacts;
- supported browsers and minimum screen sizes;
- authentication and tenancy behavior for the SPA;
- length of canary and rollback windows;
- whether live BACnet write controls ever appear in the React UI. Read-only
  commissioning does not authorize writes.

## Recommended durable tracking files in Open-FDD

When this plan is adopted in the Open-FDD repository, create:

```text
docs/migration/react-rust/
  README.md
  DECISIONS.md
  CAPABILITY_MATRIX.md
  PYTHON_EXIT_MATRIX.md
  API_CONTRACT_MATRIX.md
  PARITY_EVIDENCE.md
  CUTOVER_LOG.md
  SESSION_LOG.md
```

Update these files in the same PR as the corresponding implementation. A plan
that is not tied to code and evidence will drift.
