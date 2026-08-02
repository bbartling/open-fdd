# Test, parity, and release acceptance system

## Status semantics

| Status | Meaning |
|---|---|
| `NOT_STARTED` | no accepted implementation |
| `SCAFFOLD` | route/component/contract shape exists; behavior incomplete |
| `IMPLEMENTED` | code exists and focused tests pass |
| `VERIFIED` | real dependencies and user-visible behavior pass |
| `QUALIFIED` | release artifact passes all applicable gates |
| `WAIVED` | explicitly excluded with owner, reason, evidence, and expiry |

Only `QUALIFIED` counts as done for a shipping capability.

## Test layers

### L0 — static and source policy

- Rust format/clippy; TypeScript typecheck; real ESLint; Python offline tooling
  lint/tests where relevant.
- Dependency/license/security scans.
- No production import/dependency on Streamlit, Flask, FastAPI, pandas,
  scikit-learn, joblib, or Python executables.
- Route/OpenAPI/capability/MCP/docs inventory agreement.
- Archive, ownership, cookbook, schema, and status consistency.

### L1 — unit and property tests

- parsers, validation, unit/time conversions, feature compiler, tree/ONNX
  inference, state reducers, chart transformations, archive validation;
- min/max/just-inside/just-outside/NaN/infinity/null/unknown enum;
- property/fuzz tests for paths, archives, schemas, timestamps, and payloads.

### L2 — contract and component integration

- Axum handlers with real stores/DataFusion/model runtime;
- OpenAPI request/response fixtures;
- React components with real generated types;
- auth/role/site scope and RFC 9457 errors;
- idempotency, optimistic concurrency, cancellation, timeout, and restart.

### L3 — differential/oracle tests

For Streamlit/Python pandas and Vibe 21 oracles:

- identical frozen input and parameter set;
- raw values compared before display rounding;
- per-field absolute/relative tolerance, with exact comparison for booleans,
  enums, IDs, timestamps, and masks;
- missing/null/quality and boundary behavior;
- row masks, confirmation time, fault duration, aggregates, and ordering;
- feature vectors and model outputs;
- oracle/runtime versions and artifact hashes in the result.

A difference is either fixed, documented as an intentional contract change, or
kept provisional. It is never hidden by a broad tolerance.

### L4 — real-stack browser tests

Boot published-equivalent web and central plus real test data. No HTTP mocks in
the golden workflow suite. Cover:

- every route and primary tab;
- structured controls and keyboard navigation;
- reload/back/forward/deep links;
- uploads/downloads and artifact contents;
- errors/auth expiry/API outage/recovery;
- concurrency/stale revisions;
- job, FDD, report, twin, scenario, model, and Unity lifecycles;
- browser console/page errors and network failures.

Use mocks only for focused rare failure injection, labeled separately.

### L5 — visual and accessibility

- Fixed OS/browser/font/viewport/device-scale/theme/data/state.
- Whole-page and component-region screenshot baselines.
- Define tolerances and review all baseline updates.
- Stabilize animations, timestamps, random IDs, and chart rendering; mask only
  genuinely nondeterministic values.
- Axe, keyboard-only, focus order, landmarks/headings, labels, live status,
  contrast, 200% zoom, reduced motion, and accessible chart/table alternative.

Fix fonts/layout geometry before component cosmetics.

### L6 — artifacts and supply chain

- Model: signature/hash/schema/operator/size/resource/conformance/domain tests.
- Unity: archive traversal/bomb/symlink/file-list/MIME/hash/CSP/bridge tests.
- Reports/downloads: filename, MIME, schema, units, order, provenance, hashes.
- Containers: digest, SBOM, non-root/read-only where practical, health/readiness,
  no secrets and no Python in target images.

### L7 — performance and reliability

Record p50/p95/p99, input size, hardware, concurrency, build hash, and budgets.
Test import, FDD, analytics, inference, report, React, Unity, replay/live,
restart/recovery, disk pressure, connection loss, and multi-day soak.

### L8 — clean-host operational qualification

- clean install;
- published image pull by digest;
- representative user workflow;
- upgrade from previous qualified version;
- backup/restore;
- rollback;
- certificate/token rotation;
- audit/log/metrics verification.

## Minimum fixtures

### Analytics/FDD

- normal, one-fault, multiple-fault, boundary, missing-role, null-gap, unit
  conversion, DST, out-of-order, and long confirmation windows;
- per-rule pandas/SQL masks for every `proven` status;
- screening rules assert screening labels, not false equivalence.

### Twin/model

- every Vibe 21 strategy and phase;
- min/max and cross-field invalid action combinations;
- history and no-history;
- in-domain/marginal/out-of-domain;
- corrupt/incompatible/revoked model;
- v1/v2 schema compatibility and unsupported version.

### Unity

- missing build, valid build, incompatible bridge, revoked build, slow load,
  failed wasm, cross-origin message, selection/time/scenario exchange;
- malicious archive corpus.

### Live/replay

- duplicate, gap, stale, bad quality, reorder, reconnect, retained message,
  sequence reset, clock skew, DST, and cross-site ACL denial.

## Evidence manifest

Every milestone/qualification creates a machine-readable manifest containing:

```json
{
  "schema_version": "openfdd.qualification_evidence.v1",
  "commit": "...",
  "phase": "P2",
  "milestone": "P2-M2",
  "capability_ids": ["..."],
  "environment": {"os": "...", "browser": "...", "viewport": "..."},
  "artifacts": [{"path": "...", "sha256": "...", "kind": "test-report"}],
  "images": [{"name": "central", "digest": "sha256:..."}],
  "fixtures": [{"id": "...", "sha256": "..."}],
  "results": {"passed": 100, "failed": 0, "skipped": 0},
  "limitations": [],
  "implemented_by": "...",
  "verified_by": "...",
  "created_at": "..."
}
```

Skipped required tests fail qualification. A skip is permitted only for a
non-applicable test with an approved capability waiver.

## Release-blocking conditions

- uncaught browser errors in a primary workflow;
- fake lint or tests that skip required dependencies;
- provisional/stub computation presented as qualified;
- missing published React image or mismatched compose image;
- Python in the supported online runtime;
- model/Unity artifact without hash and compatibility validation;
- cross-site auth failure;
- critical/high unresolved security issue;
- no tested rollback or restore;
- docs contradict executable capabilities.

