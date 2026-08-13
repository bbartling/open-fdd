# Current-state audit and agent evaluation

## Audit basis and limits

This is a static code-and-document audit of:

- Open-FDD: originally `master` at `b3ff921ec981c3381b24bbfdde55c9c4d6f0ba9c`
  (2026-08-01); **refresh base for P1-M0 land:** `89fee52` (post-#650 GHCR tip
  wait + #651 product-gate false-PASS fixes). Progress ≠ Phase-1 complete.
- Vibe 21: playground `develop` at
  `bcc189a2ae3f3e374b8ffc1ea056971f3032ed7a`;
- audit date: 2026-08-01 (ledger refresh 2026-08-02).

The source repositories were read from outside the writable planning
workspace. This audit did not mutate them and did not rerun builds that require
writing dependency caches or build outputs. Existing CI configuration and
checked-in qualification records were inspected. Runtime claims must be
revalidated on a clean writable clone before Phase 1 status is changed.

## Executive scorecard

| Area | Score | Assessment |
|---|---:|---|
| Directional architecture | 8/10 | React, Rust central, DataFusion, jobs, MQTT, and MCP boundaries are largely the right shape |
| React product completeness | 4/10 | Useful shell and pages exist; major workflows are thin, placeholder, or demo-oriented |
| React SPA visual/behavior parity evidence | 3/10 | Inventories exist, but dedicated browser/a11y/visual qualification was skipped |
| Production analytics/FDD closure | 4/10 | Registry is broad; only 24/63 rules are proven and RCx is explicitly stubbed |
| Rust/Python separation | 7/10 | Production topology avoids Python, but archive/release/docs remain contradictory and several deliverables are oracle-only |
| Test and release credibility | 4/10 | Unit/build coverage exists; real-stack browser, clean-host, full-image, and soak evidence is incomplete |
| Documentation truthfulness/consistency | 3/10 | Strong detail, but completion labels outrun evidence and multiple live docs contradict the target |
| Vibe 21 prototype quality | 7/10 | Good validated concept, honest model card, assets, Unity scene, and API prototype |
| Vibe 21 production readiness | 2/10 | No WebGL build, Python-only inference, pilot multi-target model, weak runtime validation/security |
| Agent/MCP foundation | 6/10 | Read-first MCP is real; tool surface and docs lag the React/Rust product and future twin lifecycle |

**Overall:** 5/10. The agents built a credible foundation and valuable source
oracles, but the migration is not production-complete. The primary failure was
acceptance discipline, not lack of code.

## What the agents did well

### Architecture and ownership

- `frontend/web` is a real React 19/Vite application rather than a wrapper
  around product UI.
- `services/central` exposes Rust APIs for jobs, CSV ingestion, FDD, reports,
  analytics, and EnergyPlus job metadata.
- `crates/fdd_rules`, `crates/fdd_sql`, `sql_rules/`, and DataFusion establish a
  correct production direction for deterministic analytics.
- `crates/openfdd_contracts` exists and is included in the Rust workspace.
- The EnergyPlus runner contract correctly keeps execution external, rejects
  mutable image tags, constrains workspace paths, and records artifacts.
- The MCP server defaults to read-first behavior and requires explicit write
  enablement and confirmation.
- The dual pandas/DataFusion cookbook intent is explicitly documented.
- Vibe 21 refuses arbitrary uploaded joblib files and checks the artifact hash
  in its model card.
- Vibe 21 is candid that the model is `CANDIDATE`, EnergyPlus-simulated, and not
  investment-grade M&V.
- Unity is treated as a visualization client with stable entity bindings rather
  than the system of record.

### Useful implementation assets

- React routes and component primitives provide a starting design system.
- CSV import and job records provide a useful backbone for the studio workflow.
- Vibe 21 includes a real Unity project, Building 100 geometry, IDF/EPW assets,
  DR profiles, a scene, browser/API client code, and model artifacts.
- The Vibe 21 model card contains hashes, features, targets, provenance, CV
  metrics, and an explicit honesty statement.

## Material Open-FDD gaps

### 1. Phase completion was declared against reduced scope

The original exit standard required inventoried workflow closure and real
visual/behavior verification. Phase 2 qualification accepted:

- a skipped dedicated browser/accessibility/visual suite;
- RCx stubs;
- deferred site, weather, ECM, and deep error behavior;
- 38 provisional SQL ports plus one disabled/missing-role rule;
- configuration inspection in place of a clean-host no-Python runtime proof.

The scope was narrowed in closeout documents instead of marking the original
gates incomplete. Phase 1 of this program reopens those gates.

### 2. Product UI contains placeholders and prototype language

Evidence in `frontend/web` includes:

- `PlotlyHost.tsx` renders a hand-built SVG line path; there is no Plotly
  dependency, legend, axes, hover, zoom, or chart parity behavior.
- `HomePage.tsx` labels itself a “Thin Overview.”
- `MeteringPage.tsx` initializes a raw JSON textarea with sample rows and offers
  “Run RCx AHU stub.”
- `FindingsPage.tsx` has a product control that seeds `rule:DEMO` findings.
- `WattLabPage.tsx` defaults to `workspace://exports/demo.zip` and exposes only
  a handoff shell rather than the four actual studio workflows.
- Reports still state that PDF/DOCX “may be ORACLE.”
- No site/weather/ECM/digital-twin route exists in `App.tsx`.

These are acceptable scaffolds, not completed product capabilities.

### 3. Frontend quality gates are not production gates

- `npm run lint` is an echo that always passes.
- CI runs typecheck, mocked Vitest tests, and a build, but not a real browser
  suite against a running central service.
- There is no required Playwright/Cypress route and workflow suite in the main
  CI path.
- Visual baselines and same-viewport React SPA comparisons were skipped.
- Frontend Docker uses `npm install` after copying only `package.json`; it does
  not use the lockfile-driven `npm ci` reproducibility path.

### 4. Release topology contradicts “React sole product UI”

- The main GHCR stack workflow publishes `openfdd-web` from the archived
  React SPA Dockerfile.
- It does not publish the `openfdd-web` image referenced by
  `docker/compose.react.yml`.
- Its boot smoke is described as “central + React SPA.”
- The React recipe can build locally, but its default remote image is not part
  of the same proven/published stack set.
- `frontend/web` remains source- and image-active even while other docs call it
  archived.

### 5. FDD and analytics are broad but not closed

- Registry total: 63 rules.
- `proven_building_100`: 24.
- `ported_from_cookbook`: 38.
- `skipped_missing_roles`: 1.
- The parity matrix explicitly says screening SQL can differ from pandas in
  rolling, confirmation, sensor-sweep, hunting, and plant behavior.
- `services/central/src/analytics/rcx.rs` describes coverage stubs rather than
  the full reset-diagnostic behavior users expect.

Catalog presence must not be presented as behavior parity.

### 6. Agent specifications and product docs have stale conflicts

Examples:

- root guidance says React is the sole product UI;
- `frontend/web` says React SPA is the current default;
- `docs/agent/index.md` describes the runtime and UI as React SPA;
- `frontend/web/README.md` calls React a Phase 1 scaffold and says its flag is
  off by default;
- several agent-spec files say `open_fdd.contracts` is not shipped even though
  `crates/openfdd_contracts` exists;
- cookbook pages still say Open-FDD has one React product UI.

An agent cannot reliably follow contradictory authorities. Phase 1 introduces
one generated capability/ownership ledger and documentation consistency tests.

## Material Vibe 21 gaps

### What is validated

- Demand-management product question and scenario vocabulary.
- Building 100 geometry and entity-binding concept.
- A local Flask API shape for health, manifests, models, and hourly demand.
- A real Unity scene and API client behavior.
- Facility-only 40-day model results and a multi-target pilot path.
- Artifact/model-card hashes and clear synthetic-data provenance.

### What is not production-ready

- `flask_app/webgl/` contains only `README.md`; there is no checked-in or
  packaged Unity WebGL build to test.
- The bundled multi-target v2 model has 360 rows across three days and is
  explicitly thinner than the facility-only 40-day model.
- Online inference requires Flask, pandas, NumPy, scikit-learn, and joblib.
- Model cards contain Windows absolute paths to a developer machine.
- Requests are dictionary-based with defaults, not a strict versioned schema;
  unknown fields/ranges and invalid cross-field combinations are not robustly
  rejected.
- CORS permits every origin.
- Domain-of-applicability and out-of-distribution status are not calculated.
- Unit/API tests permit health 503 and skip prediction if the model does not
  load; this is suitable for a prototype, not a release gate.
- The startup manifest is large and its current shape is not yet normalized to
  Open-FDD site/building/equipment/point identity.
- Unity and Flask maintain duplicated static strategy lists.
- Unity falls back to heuristic display behavior when the API is offline; a
  production viewer must visibly distinguish frozen last-good, simulated, and
  unavailable states.

## Root-cause analysis

The implementation pattern was:

```text
large milestone -> broad scaffolding -> mocked/unit evidence -> docs mark done
```

The required pattern is:

```text
one capability slice -> executable contract -> real-stack test -> visual/data
evidence -> production image -> independent verification -> only then done
```

## Corrective policy

1. Replace binary `DONE` with `NOT_STARTED`, `SCAFFOLD`, `IMPLEMENTED`,
   `VERIFIED`, `QUALIFIED`, and `WAIVED`.
2. A capability may be `QUALIFIED` only when its evidence paths are present and
   CI-executable.
3. “Stub,” “demo,” “sample,” “oracle may remain,” and “later” in a production
   path block qualification unless explicitly waived outside the shipped UI.
4. No phase is closed by the implementing agent. A separate verification loop
   reruns its gates from a clean checkout.
5. Documentation is generated from or checked against machine-readable
   capabilities, routes, rule registry, schemas, images, and MCP tool catalogs.

