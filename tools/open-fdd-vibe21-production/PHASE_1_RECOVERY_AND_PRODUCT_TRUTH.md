# Phase 1 — Recovery, product truth, and React/Rust qualification

## Objective

Make the existing Open-FDD migration honestly production-ready before adding
the Vibe 21 surface. Preserve working code, but reopen every acceptance claim
that lacks executable evidence.

## Entry criteria

- Clean clone at a recorded commit.
- Root instructions and original migration package read.
- Current central, React, SQL registry, PyPI, Docker, GHCR, and MCP inventories
  generated from code.
- Original React SPA oracle runnable or its unavailable states documented with
  retained screenshots/fixtures.
- No phase-complete label is trusted without rerunning its gate.

## P1-M0 — Establish an evidence ledger

### PR P1-M0-A: machine-readable capability ledger

Create `docs/migration/react-rust/capabilities.yaml` with one record per user
capability:

- stable capability ID;
- route/page and user story;
- prior React SPA source location;
- React owner and central API;
- computation owner;
- status: `NOT_STARTED`, `SCAFFOLD`, `IMPLEMENTED`, `VERIFIED`, `QUALIFIED`, or
  `WAIVED`;
- evidence paths for unit, contract, browser, visual, security, performance,
  container, and docs;
- known limitations and waiver approval.

Write a validator that rejects:

- `QUALIFIED` with missing evidence;
- `WAIVED` without reason/approver/expiry;
- unknown React routes or API operations;
- the words stub/demo/sample in qualified production controls unless explicitly
  classified as demo-only;
- capabilities referenced in docs but absent from the ledger.

### PR P1-M0-B: reconcile agent and product truth

Update root and nested `AGENTS.md`, `openfdd_agent_spec`, frontend README,
service archive docs, cookbook product split, and external-agent docs to agree:

- React is the only shipping product UI;
- React SPA is a frozen oracle/archive and no image named as the product UI is
  published from it;
- Rust central and DataFusion own production behavior;
- `crates/openfdd_contracts` exists and its actual scope is stated;
- EnergyPlus is external;
- current gaps are named, not described as finished.

Add a terminology/authority consistency check to CI.

### Gate P1-G0

- The ledger validator passes.
- Every current route and prior React SPA workflow is represented.
- Contradictory UI/runtime claims are removed from live docs.
- Static grep plus a human review finds no “Phase complete” claim unsupported by
  evidence links.

## P1-M1 — Fix the supported release topology

### PR P1-M1-A: choose and codify one default topology

The recommended default is a separately built `openfdd-web` Nginx image proxying
same-origin `/api` to central. Keep React and central independently testable.

- Build with `npm ci` and a committed lockfile.
- Run as a non-root Nginx user where practical.
- Add immutable cache headers for hashed assets and no-cache for `index.html`.
- Add CSP, frame policy appropriate for the future Unity viewer, nosniff,
  referrer, and permissions policies.
- Preserve SPA fallback without swallowing `/api` 404s.
- Stamp UI commit/version and expose it in the app and health evidence.

### PR P1-M1-B: publish the actual React image

- Add `openfdd-web` to the main GHCR build/tag/digest workflow.
- Remove the archived React SPA image from the supported stack publication, or
  rename/tag it unmistakably as an unsupported oracle image in a separate
  manual workflow.
- Make compose defaults reference images the workflow actually publishes.
- Pin related images by the same release manifest/commit.
- Produce SBOMs and provenance attestations for web and central.

### PR P1-M1-C: clean-host stack smoke

Boot the published-image stack on a clean Linux host with no Python installed.
Exercise login, upload, mapping, FDD, findings, reports, and API recovery through
the browser origin. Store image digests, commands, screenshots, console logs,
and API transcripts.

### Gate P1-G1

- Published React image exists at SHA and release tags.
- A single documented command starts the supported stack.
- `docker exec`/image inspection proves no Python runtime in web or central.
- React SPA is absent from the supported running topology.
- Clean-host evidence is reproducible in CI or a controlled qualification job.

## P1-M2 — Frontend engineering baseline

### PR P1-M2-A: real lint and browser test harness

- Add ESLint with React hooks, TypeScript, import, accessibility, and no-floating
  promise rules.
- Make warnings fail CI initially for changed files, then repository-wide.
- Add Playwright with central boot fixture, authenticated session helper,
  deterministic workspace fixtures, console/page-error capture, trace/video on
  failure, and canonical desktop viewport.
- Ban network mocks in at least one smoke suite per primary workflow.

### PR P1-M2-B: error/loading/offline contract

Implement and test consistent states for:

- initial loading;
- no data;
- validation errors with field focus;
- 401/403 and expired sessions;
- 404 stale resource;
- 409 conflict/stale revision;
- 413 upload size;
- 422 contract violation;
- 429 backpressure;
- central unavailable and recovery;
- long-running jobs and cancellation.

No production workflow silently substitutes fixtures.

### PR P1-M2-C: accessibility and responsive shell

- Keyboard navigation for sidebar, tabs, dialogs, forms, tables, and charts.
- Visible focus, semantic headings/landmarks, accessible names, status live
  regions, contrast, reduced motion, zoom at 200%, and screen-reader smoke.
- Lock the canonical desktop geometry before adding responsive behavior.

### Gate P1-G2

- Lint is real and passes.
- Playwright real-stack smoke covers every route.
- No uncaught page or console errors.
- Axe critical/serious findings are zero in core states.
- API-down and recovery behavior is demonstrated.

## P1-M3 — Close visual and interaction parity honestly

### PR P1-M3-A: refresh the React SPA inventory

Record pages, controls, defaults, session state, conditional branches,
downloads, charts, tables, alerts, and representative states. Capture the
running reference at identical viewport, font, theme, data, and scenario.

### PR P1-M3-B: replace placeholder chart host

Use a maintained Plotly-compatible React integration or a deliberately chosen
equivalent that reproduces the reference. Required behavior includes axes,
units, ticks, legends, hover, zoom/pan, reset, missing-data gaps, downsample
disclosure, accessible summary, resize, export where present, and stable
screenshot rendering. The component must not be called Plotly unless it is
actually rendering the required Plotly semantics.

### PR train P1-M3-C through P1-M3-I: capability slices

Close one real-stack workflow per PR:

1. authentication and shell;
2. jobs/project context;
3. upload/import/preflight;
4. mapping and role review;
5. FDD rule selection/parameters/run/results;
6. findings/dispositions;
7. reports/downloads;
8. metering and analytics;
9. WattLab handoff and any retained pre-twin workflow.

For each slice:

- preserve labels/defaults/order/disabled behavior or record an approved
  product change;
- eliminate raw JSON entry where the reference had structured controls;
- remove seed-demo controls from production mode;
- test reload, back/forward, deep link, tab switch, and stale state;
- attach same-viewport screenshots and numerical/download parity evidence.

### Gate P1-G3

- Every in-scope capability is `VERIFIED` or explicitly `WAIVED`.
- Visual diffs meet defined regional/global tolerances.
- No placeholder chart, seed-demo action, or stub label remains in production.
- Downloads match filename, MIME, schema, units, ordering, and provenance.

## P1-M4 — Close computation gaps

### PR train P1-M4-A: SQL rule characterization

For each of the 38 `ported_from_cookbook` rules and one skipped rule:

- build a small adversarial fixture family;
- run pandas oracle and DataFusion SQL;
- compare row masks, confirmation timing, fault duration, null behavior,
  boundary values, units, and parameter overrides;
- either fix SQL and promote with evidence, or keep a named screening status and
  prevent UI/report language from implying diagnostic equivalence.

This may span many PRs by family. Do not bulk-promote registry statuses.

### PR train P1-M4-B: RCx and metering algorithms

- Define equations and required roles before coding.
- Characterize the Python/reference outputs.
- Implement actual reset, schedule, economizer, sensor-health, and plant/AHU/VAV
  diagnostics in DataFusion/Rust as appropriate.
- Keep client-side computation presentational only.
- Return raw values, units, coverage, quality, evidence windows, and warnings.

### PR P1-M4-C: report ownership

Choose a production report format path that does not require Python in the web
runtime. HTML-to-PDF may use a separate pinned non-Python renderer if required;
otherwise ship HTML/CSV/JSON and explicitly scope DOCX as an offline PyPI
deliverable. Remove “may be oracle” ambiguity from product APIs.

### Gate P1-G4

- No production capability is described as full parity while its registry says
  screening/provisional.
- Targeted rule families have golden/adversarial tests.
- RCx production endpoints perform documented calculations, not coverage stubs.
- Browser does not duplicate authoritative metering/analytics equations.

## P1-M5 — Independent requalification and archive decision

### PR P1-M5-A: production qualification pack

Run the full matrix in [TEST_RELEASE_AND_ACCEPTANCE.md](TEST_RELEASE_AND_ACCEPTANCE.md):
unit, contract, differential, browser, visual, accessibility, security,
performance, container, clean-host, upgrade, backup/restore, and rollback.

### PR P1-M5-B: React SPA retirement closure

After the evidence-retention window:

- remove React SPA from supported workflows, release images, default compose,
  CI boot smokes, and live docs;
- retain a source snapshot or screenshots/golden fixtures in an archive if
  licensing and maintenance permit;
- add a guard that rejects imports/dependencies from archived UI into production
  packages.

### Phase 1 exit gates

- P1-G0 through P1-G4 pass.
- Capability ledger has no unjustified `SCAFFOLD` or `IMPLEMENTED` status for a
  supported user workflow.
- React image and Rust central are released together and run cleanly without
  Python.
- Primary workflows pass on Chromium and one additional browser engine.
- UI, API, registry, MCP, and docs capability inventories agree.
- Rollback to the prior qualified release has been rehearsed.
- A verifier other than the implementation loop signs the evidence manifest.

## Explicit non-goals

- Do not add Vibe 21 runtime inference or Unity serving before P1-G1 and P1-G2.
- Do not redesign the UI solely for novelty.
- Do not promote all SQL rules merely to reach a zero-gap number.
- Do not delete the PyPI oracle, pandas cookbook, or engineering spreadsheets.

