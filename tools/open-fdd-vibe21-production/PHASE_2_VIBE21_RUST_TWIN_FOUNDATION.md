# Phase 2 — Vibe 21 contract extraction and Rust twin foundation

## Objective

Preserve the validated Vibe 21 behavior as an oracle while implementing its
online contracts, model inference, asset registry, and scenario execution in
Open-FDD Rust. No Unity WebGL embedding is required to exit this phase; the
React studio consumes the same APIs first.

## Entry gates

- All Phase 1 gates and exit criteria are complete.
- Vibe 21 source commit and all imported asset hashes are recorded.
- Legal/licensing review covers IDF/EPW, model artifacts, Unity assets, audio,
  textures, and third-party packages.
- Production model target is explicitly screening/operator-what-if, not M&V or
  autonomous control.

## P2-M0 — Freeze the oracle and import fixtures

### PR P2-M0-A: Vibe 21 source inventory

Create an inventory of:

- Flask routes and request/default behavior;
- `STRATEGIES`, phases, action knobs, features, lags, targets, and units;
- model v1/v2 cards and artifact hashes;
- IDF, EPW, geometry, equipment visuals, twin manifest, demand profiles;
- Unity bridge/API expectations;
- model training/farm commands and known limitations.

Classify each item `IMPORT`, `REWRITE`, `ORACLE_ONLY`, `EXTERNAL_BUILD`,
`DEFER`, or `REJECT`.

### PR P2-M0-B: golden conformance pack

Run the Flask/joblib oracle offline to generate immutable fixtures:

- nominal cases for every strategy and phase;
- min/max action bounds and representative weather/occupancy combinations;
- history vs single-row paths;
- categorical and cross-field invalid cases;
- deterministic feature vectors in exact feature order;
- expected v1 and v2 output vectors;
- floating-point tolerance and model/runtime versions;
- geometry/entity/manifest integrity fixtures.

Store JSONL/Arrow fixtures and a manifest of their hashes. Do not check in
private building data.

### Gate P2-G0

- Oracle fixtures regenerate from a pinned offline environment.
- No developer-absolute paths remain in imported manifests.
- Every Vibe 21 field has an owner, unit, range, null rule, and disposition.

## P2-M1 — Canonical Rust contracts and persistence

### PR P2-M1-A: twin contract crate

Extend `openfdd_contracts` or add a focused workspace crate containing:

- twin and twin-version manifests;
- geometry and entity bindings;
- scenario schemas/requests/results;
- model/training dataset releases;
- Unity build manifests;
- source/provenance, quality, domain status, and validation problems.

Generate JSON Schema and OpenAPI components from the Rust authority. Commit
cross-language fixture validation for Python training exporters, React types,
and Unity C# DTO generation or hand-maintained conformance.

### PR P2-M1-B: twin/job store

- Add atomic, immutable version directories under job artifacts.
- Separate draft, candidate, approved, active, superseded, and revoked states.
- Use optimistic concurrency/ETags for mutable metadata.
- Validate hashes on read and import.
- Add retention and garbage-collection rules that never remove active/referenced
  artifacts.

### PR P2-M1-C: twin APIs

Implement CRUD/version/list/bootstrap APIs with auth and site scope. Include
pagination, stable error contracts, audit records, and capability advertisement.

### Gate P2-G1

- Rust schema round-trips all accepted fixtures.
- Breaking/unknown versions fail clearly.
- ID/path traversal and cross-site access tests pass.
- OpenAPI, React types, MCP inventory, and central routes agree.

## P2-M2 — Training-to-serving model supply chain

### Decision record

Prefer an interoperable, non-executable model format such as ONNX when the
chosen Rust runtime supports the exact estimator/operators and target
platforms. Do not select a runtime solely because it can deserialize Python
objects. If ExtraTrees conversion cannot meet parity, choose one of:

1. export the forest into a small audited Open-FDD tree-ensemble format and
   implement deterministic Rust inference;
2. retrain an equivalent supported model with acceptance metrics;
3. keep the feature unavailable in production until a safe format qualifies.

Document `tract`, ONNX Runtime bindings, or a custom evaluator tradeoffs:
binary size, licensing, CPU support, WASM/ARM needs, determinism, security,
operator coverage, and maintenance. Never introduce a Python sidecar as the
answer.

### PR P2-M2-A: portable model exporter

Offline Python training outputs:

- portable model artifact;
- `openfdd.model_release.v1` manifest with relative logical names;
- exact feature compiler specification;
- conformance fixture subset;
- model/artifact/data hashes;
- metrics, domain bounds, license/SBOM, and status.

The exporter is allowed Python because it runs offline/CI, not in production.

### PR P2-M2-B: Rust feature compiler

Implement feature construction with:

- exact time/hour semantics;
- explicit timezone/DST rules;
- history ordering and missing-history policy;
- lag behavior without future leakage;
- categorical vocabulary and unknown-category errors;
- units and conversions;
- finite-number/range checks;
- no silent Flask-style defaults for missing authoritative inputs.

Differentially compare every feature vector to the frozen Python oracle.

### PR P2-M2-C: Rust inference engine

- Load only allowlisted artifact formats.
- Verify hash/signature and manifest compatibility before activation.
- Bound artifact size, tree/node count, tensor dimensions, request batch size,
  CPU time, and memory.
- Warm models before atomic activation.
- Return model release, domain status, coverage, provenance, warnings, latency,
  and typed target/unit values.
- Preserve last active qualified release on failed activation.
- Never silently fall back to demo math or Python.

### PR P2-M2-D: model registry/approval APIs

Support import, validate, qualify, approve, activate, revoke, list, inspect, and
rollback. Only authorized roles approve/activate. All changes are auditable.

### Gate P2-G2

- Rust feature vectors match oracle fixtures exactly or within documented
  numeric rules.
- Rust outputs match oracle across all golden cases within per-target tolerance.
- Corrupt, oversized, incompatible, and adversarial artifacts are rejected.
- Central and web images contain no Python/joblib/scikit/pandas runtime.
- Activation and rollback are atomic and tested.

## P2-M3 — Improve the Vibe 21 model evidence

### PR P2-M3-A: full multi-target farm release

Rerun the documented 30–50 day stratified EnergyPlus farm with:

- weather, humidity, weekday/weekend, and seasonal coverage;
- complete strategy/action design matrix;
- recovery/rebound windows;
- grouped split by day/simulation;
- no future leakage;
- facility, end-use, AHU, plant, zone, and comfort targets where source outputs
  are trustworthy.

Version source IDF/EPW, patches, EnergyPlus image digest, run manifests, failed
runs, and raw-to-training transformations.

### PR P2-M3-B: qualification and domain checks

- Compare candidate families and a persistence/physics baseline.
- Define per-target MAE/RMSE and peak-window requirements.
- Measure worst-group performance, not only global averages.
- Add physical plausibility constraints and monotonic/symmetry checks where
  justified.
- Implement in-domain, marginal, and out-of-domain classification.
- Maintain `ENERGYPLUS_SIMULATED` and `CANDIDATE` until measured BAS validation
  satisfies a separately approved gate.

### Gate P2-G3

- Pilot v2 is not the active production candidate.
- Training dataset, transform, artifact, metrics, and conformance hashes form a
  reproducible chain.
- UI/API cannot imply BAS validation or guaranteed savings.
- Domain warnings are tested and visible.

## P2-M4 — Scenario execution API and exact React preview

### PR P2-M4-A: scenario schema catalog

Serve allowed strategies, fields, ranges, steps, units, defaults, help, and
cross-field constraints from the authoritative schema. React and Unity consume
this catalog instead of duplicating lists.

### PR P2-M4-B: scenario run lifecycle

Support preview and durable runs:

- idempotency keys;
- cancellation and timeout;
- run status and logs safe for end users;
- immutable input/result artifacts;
- comparison to a named baseline;
- no-savings/negative-savings honesty;
- batch comparison for approved strategies.

### PR P2-M4-C: React engineering preview

Before Unity embedding, add a typed React view with scenario controls, exact
charts, target table, baseline deltas, provenance, domain status, and export.
This proves the model independently of the 3D client.

### Phase 2 exit gates

- P2-G0 through P2-G3 pass.
- A React user can select a qualified twin/model/weather day, run every strategy,
  compare results, inspect provenance/domain status, and export evidence.
- Rust is the sole online inference path.
- Vibe 21 Flask/joblib is retained only as a frozen oracle/reference outside
  production images.
- Scenario and model operations are represented in central OpenAPI, capability
  ledger, audit log, and MCP read tools.

## Explicit non-goals

- No claim of measured savings or M&V.
- No autonomous BAS commands.
- No Unity Editor in an Open-FDD container.
- No room geometry invented from Floor×AHU zones.
- No annual ECM product expansion until the demand-management slice qualifies.
