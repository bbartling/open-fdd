# Test, Parity, and Acceptance Strategy

## Purpose

Define what “same product” and “safe cutover” mean. Pixel similarity alone is
not behavioral parity, and matching a handful of outputs is not runtime
readiness.

## Evidence hierarchy

From strongest to weakest:

1. public-contract test against a versioned fixture;
2. end-to-end browser scenario through production-like Rust services;
3. normalized semantic comparison to an independent reference;
4. visual comparison with controlled environment and masks;
5. manual exploratory review;
6. implementation similarity.

Implementation similarity is never proof. React and Rust should not mimic
React SPA or pandas internals when a cleaner explicit contract exists.

## Parity classes

Every capability receives one or more:

| Class | What must match |
| --- | --- |
| EXACT | IDs, statuses, labels, enum values, ordering where meaningful |
| NUMERIC | Raw numeric outputs within named absolute/relative tolerance |
| TEMPORAL | Windows, timestamps, timezone, DST, confirmation/streak behavior |
| SEMANTIC | Same user meaning, even if DOM/serialization differs |
| VISUAL | Layout, density, colors, typography, charts, responsive behavior |
| INTERACTION | Defaults, state transitions, disabled/loading/error, keyboard |
| ARTIFACT | Schema/content/sections/cells; not volatile ZIP bytes |
| PERFORMANCE | Budget for latency, memory, throughput, bundle/load |
| SECURITY | Auth, authorization, input handling, isolation, audit |

## Test pyramid by implementation layer

### DataFusion SQL

- per-rule fixture tests;
- required-role and equipment applicability tests;
- parameters at min/default/max/invalid;
- missing, duplicate, irregular, and non-monotonic samples;
- confirmation-window boundary cases;
- occupied/unoccupied boundary and DST;
- query plan and representative performance;
- deterministic output ordering or explicit sort at boundary.

### Rust

- domain unit tests;
- property/fuzz tests for parsing, IDs, archives, filters, parameters;
- route/auth/error tests;
- job/run state-machine tests;
- optimistic concurrency;
- idempotency;
- cancellation and cleanup;
- artifact streaming;
- DataFusion integration;
- persistence restart/recovery.

### Contract

- OpenAPI/JSON Schema snapshots or equivalent;
- breaking-change detection;
- example payload validation;
- Rust serialization versus TypeScript type/client compile;
- backwards-read compatibility for the rollback window;
- error-code catalog completeness.

### React

- pure formatter and state-reducer unit tests;
- component tests for all widget states;
- form validation;
- query/error/retry behavior;
- route and URL-state behavior;
- keyboard/focus;
- accessibility;
- chart option/dataset semantic tests.

### Browser

- fresh authenticated session;
- reload and deep link;
- create/open job;
- upload/validate/map/run/results/download;
- rule tuning;
- plot/finding/report flows;
- permission variants;
- server error, timeout, cancellation, stale revision;
- responsive viewports;
- visual snapshots.

### Container/operations

- immutable-image startup;
- health/readiness;
- no-Python image scan;
- upgrade and rollback;
- backup/restore;
- restart during operation;
- resource and retention behavior;
- SBOM and vulnerability/license scan.

## Golden fixture protocol

Each fixture directory should contain:

```text
fixture.yaml
input/
expected/
  oracle.normalized.json
  contract.expected.json
  screenshots/
README.md
```

`fixture.yaml` includes:

- ID and schema version;
- content hashes;
- expected scenario IDs;
- data/timezone/grid/units;
- generator and seed;
- private/public classification;
- accepted tolerances;
- expected warnings/statuses.

Never refresh goldens merely because a test fails. A golden update requires:

1. explain the behavioral change;
2. identify code/contract owner;
3. compare old and new;
4. obtain domain/UI approval appropriate to impact;
5. update evidence and capability matrix in the same PR.

## Numeric comparison

Compare raw values before UI formatting.

For a numeric field `actual` and `expected`, pass only when:

```text
abs(actual - expected) <= absolute_tolerance
OR
abs(actual - expected) <= relative_tolerance * max(abs(expected), scale_floor)
```

Tolerance is per metric/rule family, not one global number. Record:

- unit;
- absolute tolerance;
- relative tolerance;
- scale floor;
- reason;
- approver;
- known discontinuities.

Exact comparison remains required for:

- rule ID;
- equipment ID;
- finding correlation key;
- status;
- applicability;
- error category;
- parameter selection;
- schema version.

Report distributional evidence, not just pass count:

- maximum and percentile absolute delta;
- maximum and percentile relative delta;
- mismatches by rule/equipment/fixture;
- skipped/missing comparison count;
- coverage denominator.

“314 pass / 54 fail” is not an exit gate without denominators, classifications,
and severity.

## Temporal comparison

Tests must cover:

- event versus ingest time;
- timezone conversion;
- DST spring/fall transitions;
- interval duration weighting;
- irregular sampling;
- inclusive/exclusive endpoints;
- streak confirmation reset;
- late/missing samples;
- window truncation at job boundaries.

Fault hours should not be inferred from row count unless the contract explicitly
defines a fixed grid.

## Visual parity protocol

Use the same:

- browser/version;
- viewport;
- device scale;
- font files;
- color scheme;
- fixture;
- auth role;
- URL and selected job/equipment/tab;
- network response payload;
- animation-disabled setting.

Compare:

- full-frame screenshot;
- sidebar;
- tab bar;
- representative form;
- metrics/table;
- Plotly chart;
- loading/error/empty state;
- narrow viewport.

Masks are allowed only for documented volatile regions such as generated IDs or
timestamps. Do not mask entire charts or primary content.

Image thresholds are triage signals. A reviewer must inspect changed regions.
Prefer DOM/CSS measurements for exact geometry and semantic assertions for
charts:

- trace names/count;
- x/y units and ranges;
- legend order;
- fault overlay count;
- hover mode;
- missing-data gaps;
- selected equipment/window.

## Interaction parity checklist

For each widget/flow:

- label and help text;
- default value;
- min/max/step/options;
- option order;
- disabled condition;
- validation timing;
- action that triggers server work;
- loading/progress;
- success/warning/error copy;
- persistence scope;
- refresh behavior;
- browser back/forward;
- keyboard operation;
- focus after action/error/modal;
- narrow-screen behavior.

React should preserve user-observable behavior, not React SPA’s whole-script
rerun implementation.

## Artifact comparison

ZIP, XLSX, DOCX, PDF, and generated manifests contain volatile metadata.
Normalize before comparison:

- sort archive entries;
- ignore approved timestamps/compression metadata;
- parse JSON/YAML structurally;
- compare spreadsheet sheets/cells/formulas/styles according to requirements;
- compare DOCX paragraphs/tables/relationships;
- compare PDF text/metadata and render pages for visual review when required;
- verify filenames, MIME types, and content disposition;
- scan archives for unsafe paths.

Define whether output compatibility is:

- byte exact;
- schema exact;
- semantic exact;
- visually equivalent;
- intentionally redesigned.

## Performance budgets

Establish baselines and budgets per workflow:

- SPA compressed bundle and initial load;
- time to usable shell;
- job list/filter;
- upload throughput and peak memory;
- validation duration;
- FDD run by dataset/rule count;
- plot dataset response and browser render;
- report generation;
- concurrent job throughput;
- historian/query memory;
- restart/recovery.

Record hardware, container limits, dataset hash, warm/cold cache, repetitions,
median, p95, and max. Avoid one-off stopwatch claims.

## Security gates

- JWT/session handling;
- role matrix per route/action;
- CSRF if cookie auth;
- CORS/CSP/security headers;
- no tokens in URLs/logs/local storage unless explicitly approved;
- upload size/count/type/traversal/symlink/compression defenses;
- safe artifact filenames;
- SQL parameter validation/injection defense;
- site/tenant isolation;
- dependency and image scan;
- secrets/config validation;
- audit for destructive actions.

BACnet live write tests remain separate and require explicit authorization.

## Accessibility gates

- semantic landmarks/headings;
- labels and descriptions;
- keyboard access;
- visible focus;
- modal focus trap/return;
- tab semantics;
- table headers/captions;
- chart summary or accessible data alternative for critical information;
- contrast;
- status announcements;
- no serious/critical automated findings;
- manual keyboard pass of core workflow.

## CI lanes

### Per PR

- formatting/lint/typecheck;
- affected Rust/SQL/React unit tests;
- contract compatibility;
- small fixture parity;
- component/accessibility;
- production build;
- policy scans.

### Merge/default branch

- full workspace;
- all public fixtures;
- browser core suite;
- visual suite;
- container smoke;
- image/SBOM scan.

### Nightly

- large synthetic/private optional fixture;
- full rule matrix;
- performance regression;
- concurrency/restart;
- broader browser/viewports;
- dependency drift alerts.

### Release candidate

- immutable images;
- clean-host deployment;
- upgrade/rollback;
- backup/restore;
- full parity and browser evidence;
- no-Python runtime scan;
- manual UX/domain approval.

## Evidence record

Every qualification record includes:

```text
date
source commit
image digests
toolchain versions
environment/hardware
fixture IDs and hashes
commands
test counts and coverage denominators
comparison tolerances
failures and classifications
waivers with owner/expiry
reviewer approvals
artifact links
```

## Acceptance rule

A capability is DONE only when its matrix row links to:

- replacement code;
- public contract;
- tests at applicable layers;
- parity evidence;
- observable operation;
- feature flag/rollback behavior;
- deletion disposition for the former Python owner.
