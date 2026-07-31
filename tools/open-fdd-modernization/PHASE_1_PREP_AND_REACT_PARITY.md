# Phase 1 — React Parity Preparation and Python Exit Readiness

## Objective

Build a production-capable React replacement behind a reversible routing flag
while shifting all required runtime behavior onto Rust and DataFusion-owned
contracts. Streamlit remains available only as the behavioral reference and
fallback during this phase. Python is frozen, characterized, and progressively
removed from the new path.

Phase 1 is complete when a user can execute the agreed end-to-end workflows in
React with no Python process involved, even though the old Streamlit deployment
still exists for comparison and rollback.

## Scope baseline

Inventory these current user-facing areas before assigning work:

- uploads and hostile ZIP/package validation;
- building/site and equipment selection;
- durable Jobs create/list/update/duplicate/archive/restore/delete;
- dataset references and session restore;
- mapping and role assignment, including VAV-to-AHU relationships;
- rule catalog, tuning, run-all/run-selected, run status, and faults;
- overview metrics and equipment inventory;
- FDD plots and fault overlays;
- RCx presets and analyst rollups;
- weather provenance and BAS-versus-reference comparisons;
- metering;
- engineering findings and human dispositions;
- report/artifact generation and downloads;
- WattLab dump/job-native handoff;
- authentication, authorization, errors, empty states, and long-running work.

The starting sources include `services/ui/streamlit_app.py`,
`services/ui/app/`, `services/ui/docs/STREAMLIT_AGENT_SPEC.md`,
`docs/migration/vibe19_parity_matrix.md`, `docs/web-app/`, and
`docs/architecture/job-workspaces.md`. The inventory must be regenerated from
code; historical matrices are evidence, not proof of current behavior.

## Definition of a vertical slice

A Phase 1 slice is not “build a component.” It contains:

1. a named user scenario;
2. a versioned API contract;
3. Rust authorization, validation, and error semantics;
4. DataFusion SQL where computation is tabular;
5. TypeScript types/client;
6. React UI and state behavior;
7. unit, contract, integration, and browser tests;
8. reference screenshots and semantic parity evidence;
9. observability and a rollback flag;
10. updated capability and Python-exit matrices.

No slice is DONE if it requires a Python process.

---

## Milestone P1-M0 — Architecture authorization and repository truth

### Goal

Replace conflicting current-state instructions with an approved future-state
decision and establish one modernization source of truth.

### PR P1-M0-01 — Modernization ADR

Changes:

- add an ADR selecting React + TypeScript for the product UI;
- select the existing central Rust service as the browser backend;
- establish DataFusion SQL as deterministic analytics/FDD authority;
- state that no FastAPI compatibility backend will be introduced;
- document the temporary Streamlit fallback and final deletion intent;
- define browser delivery approach: static assets served by central or a
  separately deployable web container, with one stable `/api` origin contract;
- document auth token/cookie, CSRF, CORS, CSP, and artifact-download direction;
- supersede the “do not recreate React” statements without erasing history.

Required tests:

- docs link check;
- architecture-policy test that rejects a production React import/client
  pointing at a Python service;
- policy test that rejects pandas/Streamlit dependencies in new production
  packages.

Acceptance:

- root `AGENTS.md`, `services/ui/AGENTS.md`, `frontend/README.md`,
  `docs/architecture/index.md`, and `docs/web-app/index.md` agree;
- no existing safety rule for BACnet, secrets, destructive workspace actions,
  or DataFusion-first execution is weakened.

### PR P1-M0-02 — Durable migration ledgers

Create and seed:

- `CAPABILITY_MATRIX.md`;
- `PYTHON_EXIT_MATRIX.md`;
- `API_CONTRACT_MATRIX.md`;
- `PARITY_EVIDENCE.md`;
- `DECISIONS.md`;
- `SESSION_LOG.md`.

Each capability row must contain:

```text
capability_id
user scenario
Streamlit/Python owner
current API/storage owner
target React route/component
target Rust module/route
target SQL view/rule if applicable
parity class
fixture(s)
feature flag
test IDs
status
deletion blocker
PR links
```

Acceptance:

- every callable Python module under `services/ui/app/` is represented;
- all `open_fdd/` production consumers are located with `rg`, imports, CLI
  entry points, workflow files, Dockerfiles, compose files, and subprocess
  calls—not merely directory names;
- unknowns are recorded as UNKNOWN, not guessed.

### Milestone gate

- architecture decision approved;
- instruction hierarchy is consistent;
- migration ledgers cover 100% of discovered production Python entry points;
- no implementation PR starts before this gate.

---

## Milestone P1-M1 — Characterization, golden fixtures, and visual baseline

### Goal

Make the current product observable and reproducible enough to replace safely.

### PR P1-M1-01 — Deterministic fixture catalog

Create small, versioned fixtures covering:

- clean single-equipment CSV;
- multi-equipment package;
- missing role;
- duplicate/non-monotonic timestamps;
- irregular sampling;
- unit mismatch;
- empty interval;
- malformed and hostile ZIP paths;
- partial weather data;
- rule pass, fault, insufficient-data, and error outcomes;
- job with mappings/config/run/findings/artifacts;
- a WattLab v3 handoff;
- representative large-data fixture generated deterministically in CI.

Each fixture receives:

- schema version;
- generation source;
- intended scenarios;
- expected timestamp and unit semantics;
- privacy/license note;
- stable content hash.

Do not commit confidential Building 100 data. Large/private datasets remain
optional qualification inputs.

### PR P1-M1-02 — Python reference exporter

Add the minimum Python instrumentation necessary to emit canonical JSON for
current behavior:

- normalized input manifest;
- resolved equipment and role mappings;
- effective parameter values;
- rule results and statuses;
- rollup metrics;
- finding identities/correlation keys;
- report/artifact manifest;
- warnings and error categories.

Reference JSON must:

- sort keys and unordered collections;
- use an explicit timestamp format and timezone;
- encode missing/NaN/Inf deliberately;
- include engine, registry, code, and fixture versions;
- avoid volatile generated timestamps in compared payloads;
- distinguish raw numeric evidence from display rounding.

This exporter is an oracle tool, not a new production service.

### PR P1-M1-03 — Streamlit interaction and screenshot baseline

For every in-scope scenario, capture:

- initial route/page;
- sidebar state;
- tabs and expanders;
- widgets with labels, help, defaults, ranges, and disabled rules;
- metric cards;
- tables, charts, legends, hover modes, and download controls;
- loading, success, warning, error, and empty states;
- narrow and desktop viewport screenshots;
- keyboard focus order for primary workflows.

Store a machine-readable interaction manifest alongside screenshots. Mask
unstable values and define permitted screenshot regions explicitly.

### Tests and targets

- reference export repeatability: byte-identical normalized JSON across three runs;
- fixture parser coverage: every error class has a test;
- UI scenario coverage: 100% of capability rows have at least one baseline
  screenshot or an explicit NONVISUAL classification;
- zero unexplained network calls in captured Streamlit flows.

### Milestone gate

- golden artifacts can be regenerated with one documented command;
- parity evidence names exact source commit and fixture hashes;
- baseline includes failures and empty states, not only the happy path.

---

## Milestone P1-M2 — Rust web contracts and platform foundation

### Goal

Give React a stable, typed, observable Rust API without copying Streamlit’s
session-state architecture.

### PR P1-M2-01 — Contract conventions

Define cross-route conventions:

- `/api/v1` version boundary or an equivalent documented compatibility policy;
- request IDs and trace IDs;
- RFC 3339 timestamps with timezone rules;
- decimal/float missing-value representation;
- pagination, filtering, and sorting;
- optimistic concurrency revisions;
- idempotency keys for mutating/long-running operations;
- structured error envelope;
- job/run status vocabulary;
- artifact metadata and safe download names;
- capability/version endpoint;
- cancellation semantics.

Recommended error envelope:

```json
{
  "error": {
    "code": "mapping.role_missing",
    "message": "Human-readable summary",
    "details": {},
    "retryable": false,
    "request_id": "..."
  }
}
```

Generate or verify TypeScript types from the contract source. Add a breaking
change check to CI.

### PR P1-M2-02 — React project and delivery shell

Create a production React/TypeScript project with:

- pinned Node/toolchain versions;
- strict TypeScript;
- lint, format, unit test, component test, and production build;
- route/error boundaries;
- API client with auth and request IDs;
- environment/config validation;
- design tokens;
- test selectors based on semantic IDs rather than CSS layout;
- bundle analysis and dependency-license/security checks;
- container/static delivery path.

Do not import a large component library until a short evaluation proves it can
match the Streamlit geometry and interaction requirements. Wrapping primitives
behind local components makes later library experiments reversible.

### PR P1-M2-03 — Async operation substrate

Add or normalize Rust operations for:

- create operation;
- poll/get status;
- progress and current stage;
- cancel where safe;
- retry classification;
- result/artifact links;
- bounded logs/events;
- operation expiry/retention.

React must not hold an HTTP request open for long FDD/package/report work.
Choose polling initially unless SSE is already justified; preserve an event
contract that can later support SSE/WebSocket.

### Tests and targets

- Rust unit tests for every error variant and state transition;
- schema snapshot/compatibility tests;
- generated TypeScript compiles with `noUncheckedIndexedAccess` or an equivalent
  strictness policy;
- auth tests for viewer/operator/admin on every route family;
- invalid request fuzz/property tests for package names, IDs, and filters;
- central can serve the production SPA and API in the selected topology.

### Milestone gate

- a minimal authenticated React shell loads from a production-like container;
- health/version/capabilities work;
- contract CI blocks undocumented breaking changes;
- no Python service is required.

---

## Milestone P1-M3 — Pixel/interaction parity shell

### Goal

Reproduce the recognizable Streamlit application frame before migrating deep
features.

### PR P1-M3-01 — Layout and design-token parity

Implement:

- page max width and gutters;
- top chrome and title/caption rhythm;
- Streamlit-like sidebar width, padding, collapsed behavior, and sections;
- top-level tabs with exact order, labels, active indicator, and overflow;
- cards, borders, radius, shadows, typography, muted text, and status colors;
- responsive stacking behavior;
- skeletons/spinners and alert styles;
- dark/light behavior if the reference supports it.

Use screenshots at the same viewport, browser, device scale, font availability,
fixture, and state. Record numeric CSS measurements for critical geometry.

### PR P1-M3-02 — Widget primitives

Build local parity components for:

- select/multiselect;
- slider/range slider with Streamlit-equivalent keyboard behavior;
- checkbox/radio/toggle;
- file upload/drop target;
- button and download button;
- tabs;
- expander;
- metric card/delta;
- dataframe/table;
- progress/status;
- Plotly host;
- confirmation modal;
- toast/inline alert.

Every primitive must define:

- controlled value contract;
- disabled/loading/error behavior;
- accessible name and description;
- keyboard actions;
- focus ring;
- density;
- test ID convention.

### PR P1-M3-03 — Navigation and session semantics

Map Streamlit rerun/session behavior to explicit React state:

- URL state for shareable page/tab/job/equipment selection;
- server state through a query cache;
- form draft state locally;
- durable domain state only through Rust APIs;
- no critical state exclusively in `localStorage`;
- predictable restore after refresh/back/forward;
- dirty-form warning where appropriate.

### Tests and targets

- component tests for all states and keyboard paths;
- automated accessibility scan with no serious/critical findings;
- representative visual diff thresholds:
  - critical frame regions: <= 0.5% changed pixels after masks;
  - component regions: <= 1.0%;
  - charts: semantic assertions plus looser image threshold;
- manual parity checklist completed by a reviewer who did not author the component.

### Milestone gate

- a user can view the two apps side-by-side and identify no material shell,
  navigation, control-density, or interaction-order difference;
- deviations are documented and approved, not accidental.

---

## Milestone P1-M4 — Job and CSV vertical slice

### Goal

Complete the first valuable Python-free workflow:

```text
create/select job -> upload package/CSV -> validate -> map -> persist config
-> run SQL FDD -> inspect results -> download artifact
```

### PR P1-M4-01 — Jobs React client

Consume central’s Rust job source of truth:

- list/filter active and archived jobs;
- create, open, update metadata;
- duplicate semantics that exclude runs/findings/reports;
- archive/restore;
- confirmed delete with revision/idempotency behavior;
- conflict UI for stale `meta_revision`;
- deep links to active job.

Do not mirror `workspace/jobs/` in browser storage.

### PR P1-M4-02 — Rust upload/package ingest

Move package behavior needed by React into Rust:

- streaming multipart upload with size limits;
- safe temporary storage;
- ZIP traversal, symlink, compression-ratio, file-count, and extension defenses;
- content sniffing rather than filename trust;
- deterministic validation report;
- dataset registration and job reference;
- cleanup on failure/cancellation;
- resumability decision recorded explicitly.

### PR P1-M4-03 — Mapping and validation UI

Implement:

- equipment inventory/tree;
- physical column to logical role mapping;
- unresolved/ambiguous role states;
- VAV/AHU relationships;
- units and sampling-health display;
- revisioned save/restore;
- validation blockers versus warnings;
- downloadable mapping/validation manifest.

Rust role resolution must align with existing `fdd_core` behavior and documented
oracle differences. Do not hide missing roles with guessed mappings.

### PR P1-M4-04 — Run and results UI

Implement:

- run all/selected rules;
- effective parameter display;
- async progress, cancellation/retry rules;
- per-rule succeeded/skipped/failed outcome;
- fault table, filtering, equipment drilldown;
- evidence rows and correlation keys;
- CSV/JSON artifact download.

### Tests and targets

- hostile archive security suite;
- upload cancellation and cleanup tests;
- job revision conflict integration test;
- exact status/ID parity;
- numeric parity at tolerances in the test strategy;
- browser test of the entire workflow in one fresh session and after page reload;
- 500 MB synthetic upload target without unbounded memory growth, with final
  threshold adjusted to supported deployment constraints;
- no Python process/container present in the test topology.

### Milestone gate

- the full slice works against Rust services and DataFusion;
- artifacts are deterministic enough for semantic comparison;
- Streamlit remains a selectable fallback, not a dependency.

---

## Milestone P1-M5 — Analytics, plots, findings, reports, and WattLab

### Goal

Move remaining user value in bounded domain slices. Do not port pandas
dataframe code line-for-line into TypeScript or Rust.

### PR family P1-M5-A — Rule tuning and catalog

- one rule metadata source;
- parameter types, units, bounds, defaults, aliases, applicability, and parity
  status supplied by Rust;
- typed parameter binding into DataFusion templates/parameters;
- session/job-scoped parameter revision;
- slider and advanced numeric-entry parity;
- validation prevents invalid SQL substitution.

Tests:

- registry unique IDs and aliases;
- defaults/bounds agree across registry, API, React, and SQL;
- parameter property tests;
- injection and malformed-input tests.

### PR family P1-M5-B — FDD and RCx plot datasets

Add API dataset contracts, not chart HTML:

- series metadata;
- timestamps and values;
- units;
- fault intervals/markers;
- downsampling policy and provenance;
- missing-data segments;
- equipment and query identity.

React builds Plotly figures. DataFusion performs filtering, joins, aggregation,
and downsampling after fault math.

Tests:

- dataset semantic snapshots;
- min/max/extrema preservation under downsampling;
- timezone and missing-segment tests;
- chart trace count/name/axis/legend assertions;
- performance budgets for large windows.

### PR family P1-M5-C — Analytics and metering

Port each current pandas analytics function using:

```text
characterize -> name required roles/units -> express in DataFusion SQL
-> compare to oracle -> expose typed result -> render -> retire Python caller
```

Start with high-use rollups:

- motor/weekly runtime;
- comfort percentage;
- zone/plant summaries;
- weather bins/comparisons;
- metering totals and periods;
- mechanical-cooling evidence.

Every metric must expose formula/rule version, data window, equipment scope,
sample coverage, and warnings.

### PR family P1-M5-D — Findings and dispositions

Use the existing principle that machine evidence and human disposition are
separate:

- stable `finding_id` and `correlation_key`;
- immutable or append-only machine evidence revision;
- optimistic concurrency for disposition;
- status, notes, author, timestamps, and audit trail;
- filters and bulk operations with explicit confirmation.

### PR family P1-M5-E — Reporting and export

First inventory required formats:

- raw CSV/JSON;
- workbook preview/download;
- DOCX/PDF if actually supported;
- package/export ZIP;
- WattLab v3 offline dump;
- job-native WattLab handoff.

Implement generic generation in Rust or a deliberately selected non-Python
service/library. If a format library is inadequate, record the product decision
instead of retaining an accidental Python production worker.

Tests:

- archive manifest and schema;
- semantic cell/section comparison;
- safe filenames and content disposition;
- golden artifact normalization;
- large artifact streaming;
- WattLab consumer compatibility.

### Milestone gate

- every in-scope capability is DONE or has an approved defer decision;
- no React screen calls an endpoint implemented only for Streamlit;
- no deterministic analytics remains on the new path in pandas.

---

## Milestone P1-M6 — Python exit readiness and release candidate

### Goal

Prove the new path is independently deployable and prepare a safe Phase 2.

### PR P1-M6-01 — Python exit matrix closure

Classify every Python item:

| Class | Meaning |
| --- | --- |
| DELETE-P2 | production twin replaced and deletion evidence complete |
| ORACLE-ONLY | retained for tests/reference; excluded from product images |
| ARCHIVE-DECISION | value exists but ownership/location requires product call |
| BLOCKED | replacement incomplete; Phase 1 cannot exit |

Search:

- imports;
- entry points;
- Dockerfiles/compose;
- workflows/scripts;
- docs commands;
- subprocess invocation;
- package extras;
- test fixtures;
- generated artifacts and runtime images.

### PR P1-M6-02 — Independent React/Rust image stack

Add a production-like stack profile with:

- React/web artifact;
- central;
- fieldbus where appropriate;
- MQTTS broker;
- no UI Python image;
- health/readiness;
- immutable version manifest;
- logs/metrics/traces;
- backup/restore and upgrade notes.

### PR P1-M6-03 — Phase 1 qualification

Run:

- Rust format/clippy/test;
- Node lint/typecheck/unit/component/build;
- contract compatibility;
- full browser matrix;
- parity suite;
- security scans;
- upload/load/soak tests;
- restart/recovery;
- upgrade from current persisted jobs;
- rollback to Streamlit against unchanged data where supported.

Publish evidence with exact commit, image digest, fixture hashes, environment,
commands, failures, waivers, and reviewer approvals.

### Phase 1 exit gate

All must be true:

- React is feature-complete for the approved scope behind a flag;
- a production-like stack runs with no Python;
- API contracts are versioned and compatibility-checked;
- semantic and visual parity gates pass;
- security and performance budgets pass;
- Python exit matrix has no BLOCKED row;
- rollback is tested;
- Phase 2 deletion PRs are enumerated but not prematurely executed.

## Phase 1 anti-patterns

- building React against a temporary FastAPI sidecar;
- reproducing `st.session_state` as one global React object;
- calling the filesystem directly from the browser;
- porting pandas code to TypeScript;
- marking UI parity done from a static screenshot;
- comparing rounded card text instead of raw result payloads;
- deleting the oracle before independent parity is established;
- combining UI shell, API redesign, SQL rewrite, and deletion in one PR;
- using a moving container tag as release evidence;
- treating a skipped rule as a successful rule;
- hiding unknown or unsupported behavior behind a generic empty state.
