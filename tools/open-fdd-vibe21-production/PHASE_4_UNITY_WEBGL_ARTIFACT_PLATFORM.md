# Phase 4 — Unity WebGL artifact validation, serving, and React integration

## Objective

Let an external Unity pipeline deliver a zipped WebGL build that Open-FDD Rust
validates, versions, serves, embeds, observes, and rolls back. Open-FDD never
contains or invokes the Unity Editor in production.

## P4-M0 — Artifact contract and threat model

Define `openfdd.unity_webgl_build.v1`, accepted Unity versions, compression
profiles, file patterns, MIME types, maximum compressed/expanded bytes, maximum
file count/depth, required entry points, bridge version, CSP needs, browser
support, and legal metadata.

Threats include zip-slip, symlinks, archive bombs, active HTML/JS supply-chain
content, untrusted `.wasm`, cross-site messaging, API token exposure, persistent
XSS, CSP bypass, oversized memory, and stale/incompatible builds.

### Gate

- Security review and adversarial archive fixtures exist before upload is
  enabled.

## P4-M1 — Rust import and immutable storage

### PRs

- Multipart or direct-to-object-store upload with streaming limits and digest.
- Validate archive before extraction; extract into a temporary isolated path;
  atomically publish only after every check passes.
- Require `index.html`, loader/framework/data/wasm files as declared by manifest.
- Verify every file hash and reject undeclared executable content.
- Record uploader, time, Unity version, source commit, artifact hash, scan/SBOM,
  compatibility, and validation result.
- Candidate/approved/active/revoked lifecycle with atomic activation/rollback.

### Gate

- Zip-slip, symlink, duplicate-path, case-collision, bomb, oversize, corrupt,
  wrong-MIME, missing-entry, and hash-mismatch tests pass.

## P4-M2 — Same-origin static serving

### PRs

- Serve immutable build paths such as
  `/twins/{twin_id}/builds/{build_id}/...`; never expose filesystem paths.
- Correct `.wasm`, `.data`, `.js`, `.json`, compressed variant, range, ETag,
  cache, and nosniff behavior.
- Serve `index.html` with a narrow CSP and no cache; hashed bulk assets immutable.
- Apply authentication/authorization to bootstrap and private artifacts while
  supporting Unity loading semantics.
- Do not put bearer tokens into URLs, logs, build files, or WebGL local storage.

### Gate

- Header/content checks pass through the actual reverse proxy and supported
  deployment topology.
- A revoked or cross-site build cannot be fetched.

## P4-M3 — React host and bridge

### PRs

- Add a viewer host with load progress, compatibility check, retry, full-screen,
  explicit version/status, error detail, and no-WebGL fallback.
- Implement the versioned strict-origin `postMessage` bridge from target
  architecture.
- Synchronize equipment selection, time cursor, scenario result, and visual mode
  without duplicated authority.
- Keep exact engineering values in React charts/tables; Unity visualizes spatial
  context and interaction.
- Disable or clearly mark any Vibe 21 heuristic fallback. Never label heuristics
  as current model output.

### Gate

- Playwright loads a real qualified build, waits for `viewer.ready`, exchanges
  selections/scenarios, captures console errors, and verifies fallback states.

## P4-M4 — External Unity build handoff

The Unity repository/pipeline must:

- pin Unity and package versions;
- generate the build manifest and file hashes;
- use stable Open-FDD entity bindings and bridge DTOs;
- consume schema/strategy catalog rather than a duplicated static list;
- use page origin in WebGL and configurable local central URL in Editor;
- run Unity edit/play tests plus a headless/browser build smoke;
- produce `unity_webgl_build.zip`, manifest, SBOM/license notice, screenshots,
  smoke report, and source commit;
- never include training data, secrets, local paths, or joblib.

## P4-M5 — Performance and operations

- Establish size, cold-load, warm-load, memory, CPU/GPU, FPS, API-latency, and
  crash budgets for representative hardware.
- Add viewer telemetry that excludes sensitive building values by default.
- Test content delivery behind TLS, range requests, slow networks, cache
  invalidation, interrupted loads, multiple viewers, and central restart.
- Rehearse activation, rollback, revocation, and garbage collection.

## Phase 4 exit gates

- A real Vibe 21-derived Unity WebGL build is imported and served by Rust.
- React and Unity complete selection/time/scenario bridge tests.
- No Flask/static Python server is required.
- Artifact security suite, browser matrix, performance budgets, and rollback pass.
- Missing/incompatible/revoked build states remain fully usable in React.

