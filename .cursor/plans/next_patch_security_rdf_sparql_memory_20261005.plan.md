---
name: Next patch — security, real Haystack RDF, SPARQL UI/API and memory resilience
overview: Independent audit follow-up for 3.5.65/215e159. Reconcile Grok evidence, correct product and evaluator defects, deliver real graph-driven consumers and a bounded read-only SPARQL editor/API, finish issue1127 acceptance, then release a tiny patch. All implementation is pending.
todos:
  - id: intake
    content: Preserve active work, bind current source/candidate/Grok evidence and reopen incomplete acceptance claims.
    status: completed
  - id: security-controls
    content: Resolve private application/tenant/role/archive/connector findings and prove real middleware/storage enforcement.
    status: in_progress
  - id: evaluator-integrity
    content: Eliminate reproduced false-PASS paths in real security, MQTT, ZAP and model wrappers.
    status: in_progress
  - id: memory-durability
    content: Finish issue1127 admission, cancellation, global byte bounds, durable receipt/spool behavior and portable sizing.
    status: pending
  - id: rdf-semantics
    content: Complete pinned-defs semantics, inheritance, projection constraints, stable scope/revisions and typed readiness.
    status: pending
  - id: real-consumers
    content: Connect graph bindings to actual DataFusion FDD/history and an independently checked external ECM calculation.
    status: pending
  - id: sparql-editor-api
    content: Add Data Model SPARQL panel, mechanical query buttons and a secure bounded read-only API for UI and AI agents.
    status: pending
  - id: camber-crosscheck
    content: Fix verified rule-tuning/readiness gaps and add pinned independent M&V vectors, versioned export metadata and external findings contracts.
    status: pending
  - id: qualification
    content: Execute independent known-answer/negative/integration/resource tests and reconcile Grok candidate results.
    status: pending
  - id: release-docs
    content: Update honest docs/milestones/issues, bump the next available patch once, verify Actions/GHCR/candidate and hand over closure evidence.
    status: pending
isProject: true
---

# Cursor entry point: next revision after the 2026-10-05 independent audit

## Read first

This is a new continuation plan, not a completed implementation. Audit source is **3.5.65 / `215e1594675e8a6b8a113dc0399950ab649ba2a4`**. Current GitHub master and VERSION must be rechecked before implementation; Grok and other agents can land intervening changes. The primary checkout was still `4251505` with active edits at audit time. Do not reset, overwrite or blindly pull those files. Use the existing suitable worktree/PR or a separate checkout and reconcile newer master safely.

Detailed findings and synthetic counterexamples are local/private at:

**`/home/ben/Documents/Codex/private_audits/openfdd_20261005_215e159/README.md`**

Read that entry, `SECURITY_AUDIT.md`, `RDF_AUDIT.md`, `QUALIFICATION_AUDIT.md`, `MEMORY_1127_AUDIT.md`, and `CAMBER_REVIEW.md`. They bind exact source lines, claims, limitations and reproduced failures. Preserve this directory outside Git. Follow `SECURITY.md` for unresolved vulnerability details; public fixes/release notes describe corrected behavior and validation without publishing attack instructions or credentials.

Read root `AGENTS.md`, `openfdd_agent_spec/AGENTS.md`, architecture/ownership, `HAYSTACK_RDF_ROLLOUT.md`, `SECURITY_QUALIFICATION_POLICY.md` and canonical skills. Existing audit plans, MILESTONES, bug ledgers and Grok evidence remain historical records. Append/correct prospective status with evidence rather than erasing history or simply checking todo boxes.

## Audit conclusion and priority

Cursor landed useful changes: official vocabulary artifacts and RDF serialization, real Oxigraph SELECT templates, native metadata revisions, shared DataFusion runtime, some actual worker admission, Arrow result bounds, and expanded security policy/tests. Latest master Actions and publishers are green.

The audit also found **product control gaps, real false-PASS evaluator counterexamples, incomplete RDF semantics/consumers, unmeasured performance and remaining issue1127 resource/durability work**. Code delivery, offline detector tests, real application acceptance, deployed candidate smoke, full stress and licensed assessment are separate claims. A healthy HTTP response or green workflow cannot substitute for an omitted assertion.

Prioritize actual security controls and evaluator correctness, then the remaining memory/ingest controls. Build the new query editor on a correct scoped model and controlled execution service. Deliver bounded PRs by concern; publish progress frequently using the user's existing PR workflow. Do not mix all changes into one enormous PR.

## P0 — reconcile current source, Grok and issue ownership

1. Record current master/worktree/PR SHAs, VERSION, exact running images/digests/platforms, relevant config/policy/fixture/defs/harness hashes and Grok report location. Source audit does not establish the currently deployed image.
2. Read Grok's newest issue comments and artifacts. Add each new reproducible failure to a worklist with issue link, source/candidate, symptom, independent expected result, actual result, owner, fix PR and required retest. Reproduction details for security stay private.
3. Deduplicate against this audit and existing #999, #997/#1000–#1004/#1123, #1127 and header issues #1130–#1132. Read private finding IDs before assigning work. An existing closed implementation issue must be reopened or explicitly tracked by a linked residual issue if its required behavior is absent; do not leave an unmet feature silently CLOSED.
4. Hold #997/#1003/#1004/#1123, #999 and #1127 closure until their applicable criteria are met. A smoke on the same deficient harness cannot close the demonstrated gaps. #1000 requires first-create/delete crash and concurrent-initial-import transaction evidence; the improved CAS does not yet prove those windows safe. #1002 requires actual consumers; returned plans alone do not satisfy it. Strict projection conformance must be reconsidered against the independent negative cases before claiming #1001 complete.
5. Agree bounded resource/test windows with the existing Grok ownership. Avoid duplicate live stress and conflicting deployments. This plan itself authorizes no BAS writes or provider-network scanning.

## P1 — product security and real enforcement

Use private `SECURITY_AUDIT.md` as the exact fix list. Cover every production router, including separately merged/legacy feature routers, with the canonical method/role/object policy inventory. Include new model/dataset/SPARQL/history/cache/export surfaces. Server-side tenant/object/role enforcement must be shared and independent of UI restrictions.

Required acceptance includes valid Admin, Tenant A/B operator, Viewer and Agent identities with populated own/foreign fixtures; owner-positive existence/readback controls; symmetric foreign denials; viewer mutation denial without state changes; correct hub-admin behavior; session/job/dataset/kit/stream object resolution; clean JWT expiry/revocation/session handling where supported; bounded parser/archive paths; private connector management; appropriate command identity. Prove middleware and storage behavior with real Rust integration tests, not source-string checks or a fake server alone.

Repair selected OT HTTPS recipes as complete supported recipes: Caddy + React + central + exactly one selected connector, broker optional, central/management private, reachable authenticated ingestion and connector diagnostics. Validate both BACnet/Modbus host-network and Haystack bridged/network cases. Do not assume the old HTTPS overlay composes with every new recipe. Require resolved `docker compose config` and disposable actual startup/peer positive-negative evidence. CA trust persistence/distribution, hostname validation, wrong/untrusted/expired certificate, restart and plaintext redirect behavior need their own proof. Licensed Nessus remains separate.

Address #1130–#1132 using exact plugin/route evidence and measured application risk. Do not blanket-suppress findings or weaken CSP to turn a scanner green. Apply security headers consistently on successful, denied and error responses, with trusted proxy source/scheme handling. Record scoped Medium dispositions only when justified, owned, expiring and retested.

## P2 — evaluator and Python/ZAP/MQTT/Nessus assurance

Read `QUALIFICATION_AUDIT.md` and run its **actual production-wrapper** counterexamples before fixing. Each must currently fail its expected assertion, then become a permanent regression that rejects the broken report after correction. Do not edit the independent expected results to match the defect.

- Recompute verdicts from a versioned required check set and real observations. Reject unknown/duplicate/disappearing IDs, contradictory counts/statuses and claimed top-level PASS when child evidence is failed, empty or incomplete.
- Required N/A needs explicit applicability evidence; BLOCKED/ERROR/SKIPPED cannot qualify. Validate candidate/config/fixture/policy identity, timestamp/freshness and local artifact existence/content hashes; a helper trusting caller booleans is insufficient. Keep synthetic inputs labeled synthetic.
- Every foreign denial needs a valid authenticated owner-positive control. Missing/empty/non-JSON/HTML own responses must not qualify. Run both tenant directions and role mutation readback. Apply declared finite request/response/cleanup/deadline budgets.
- MQTT qualification requires real broker observer and generated identity/ACL evidence with the required named checks; top-level fields cannot override failed/missing checks. Pair permitted traffic and foreign/wildcard/command denial with expected payload identity. Keep transport continuity and durable commitment distinct.
- ZAP needs pinned tooling, completed jobs, exact scope and authenticated scanner traffic with successful protected response evidence. Passive scan success, a separate login, a URL string in an alert or mocked scan output cannot establish authenticated API coverage. Add disposable real web+central/role/route tests and browser/header checks.
- Nessus readiness, importer tests, image scans, host exposure/TLS and an actual licensed credentialed assessment stay distinct. Reject incomplete/stale/foreign/unassessed/partial-credential/OT-early-stop/synthetic evidence as appropriate. No license means the actual assessment remains BLOCKED, while readiness work continues.
- Gate36 must assert actual RDF vocabulary/constraints, expected nonempty fixture inventory, both owners/foreign directions, real SPARQL known answers and ECM math. A catalog response plus rejected free-form text does not prove semantic query correctness.

Extend real existing scripts and canonical inventory rather than making a parallel harness. Use versioned [OWASP ASVS 5.0.0](https://owasp.org/projects/asvs) requirements as a coverage map, with tested/untested/applicable status; do not claim compliance from a list alone. Automation and expert review provide different evidence; avoid superiority or universal-security claims.

## P3 — finish #1127; protect collection while bounding computation

Read `MEMORY_1127_AUDIT.md`. Retain the new shared pool and worker-owned permits, then finish the gaps:

1. Common actual admission/byte reservations for analytics, series, FDD/AFDD, imports, graph queries/materialization, exports, cache work and compaction. Scope/class fairness and bounded queues are needed. Cache hits may serve valid last-good results while expensive recomputation is deferred.
2. Actual effective cgroup v2/v1 process/mount/ancestor limits, visible shared-parent pressure and honest bare-metal/unknown fallback. Validate CPU/memory overrides and supported small-host profiles. Auto-sizing must preserve OS/ingest/control/storage headroom; a plan tier or leaf-only value is insufficient.
3. Cancellation through the current SQL/graph stream, batch/rule boundaries and immediately before publication/checkpoint. Test cancellation during a **single last rule**, disconnect and shutdown. Permit release means worker teardown, not returned timeout or cleared Actions.
4. Global Arrow/JSON/import/cache/graph bytes and staging bounds. Count actual conservative serialized/owned size, not a fixed bytes-per-row estimate after allocation. Acquire before large request staging/decompression; stream bulk outputs and bound spill/free disk.
5. Compact terminal payloads in the **live** receipt map; preserve durable dedupe identities with a tested replay/retirement horizon. Bound writer commands and all per-scope buffers by aggregate bytes, including failure retention.
6. Correct durable MQTT receipt/spool/ack boundaries and persistent retry semantics. Client enqueue or broker PubAck alone is not canonical historian commitment. Keep broker-free local HTTP's positive committed receipt contract. Preserve pending envelopes and surface finite storage/retention exhaustion.
7. Explicit CI execution of `fdd_resources` tests; add real combined workload/cancellation/replay qualification rather than relying on simulated `protect_ingest=true` flags.

Keep **one canonical Parquet writer**. Rust stays the product runtime, Arrow stays the execution format and DataFusion stays time-series/FDD compute. A later supervised compute-worker process can provide a real failure boundary; adding central replicas against a shared writable Parquet volume is not the fix. Pi3 remains fieldbus-only until a larger profile is independently qualified.

## P4 — finish Haystack RDF correctness and true consumers

Read `RDF_AUDIT.md`; its parser/validator negatives and subtype queries define independent acceptance. Fix these using the actual pinned official defs rather than a new OpenFDD HVAC vocabulary.

- Validate exact per-library IRIs/hashes/dependencies, metadata kinds/units/references/cardinality and stable scoped identity. Preserve legitimate duplicate sensors; typed FDD selection must report ambiguity and accepted evidence separately. Preserve JSON/ZIP and native rich metadata compatibility with explicit omissions.
- Materialize the required ontology/inheritance view, or derive a semantically equivalent verified closure. Queries must handle relevant AHU/equipment subtypes using actual defs; an `rtu`/`doas`/`mau` fixture must not disappear merely because the template tests only direct `ahu`. Do not assert ontology is loaded when only instance triples exist.
- Keep pinned vocabulary/ontology in a separate graph from authoritative tenant instances. The audited defs contain 109 equipment and 471 point prototype resources; importing these into the default instance inventory would corrupt mechanical counts. Inheritance may consult vocabulary, but counting and equipment/point selection must range only over the authorized instance graph. Test both graph separation and closure using independently known counts.
- Standard semantic facts must affect applicability/bindings through actual SPARQL, not silently be injected from an authoritative-looking inventory field after a SELECT. Define and validate conflicts between compatibility stamps/roles and accepted semantic assertions.
- Make the FDD binding plan an actual input to a real production DataFusion/registry run. Make approved history/provider binding an actual scoped data-read input. Make the external ECM adapter perform at least one generic calculation using selected model quantities/units/evidence and the existing `open_fdd.ecm_engineering` formulas. Python remains outside central.
- Hold telemetry fixed; change only the accepted model/selection/topology and prove the predicted FDD/input/ECM outcome changes. Remove/corrupt the binding and require an explicit unready result, not a silent sidecar bypass. Check dimension conversions and independently computed expected energy values.
- Include scope/model/defs/binding/query/fixture revisions in derived caches and results; test update/delete/reimport/concurrent CAS/restart/rollback invalidation. Byte-bound and retire old graph snapshots.
- Parse **actual Rust/API exporter bytes** independently in CI. A committed snapshot fixture is useful evidence for that fixture, not proof the current API still emits it. Known-answer tests must validate every supported standard term, units/refs/function constraints, inherited types and exact scope.
- Measure defined cold/warm rebuild/query/export/invalidation/concurrency/RSS/cancellation budgets on suitable capacity. A performance budget document is not a measurement; unrun scale stays PARTIAL.

Native package authoring/import remains ZIP + JSON; RDF is a derived committed model view. SPARQL handles semantics/relationships; DataFusion handles Parquet telemetry math. No vendor, campus, equipment-label prefix or test-bench special case in product selection.

## P5 — requested Data Model SPARQL editor and AI API

Extend existing **`frontend/web/src/pages/MappingPage.tsx`** with a **SPARQL** panel beside Mapping and Results by Category. Reuse the locked active site/session and existing auth, without inventing another building selector. Keep ordinary results as readable tables/scalars, not raw JSON. The user asked for editable query text, prepopulated by buttons like the older Python application; the implementation is React + Rust.

### UI and curated query catalog

- Labeled accessible multiline/code input showing real SPARQL text, populated with a useful count/summary initially.
- Buttons/templates: equipment count; equipment by semantic type; points by kind/unit; AHUs and served terminals; unresolved input bindings/topology; approved engineering metadata/history links. Use `COUNT(DISTINCT ...)` and appropriate inheritance so multi-tagged equipment is not double-counted. Derive field/class IRIs from the supported defs pin. Template labels are presentation, not selectors.
- Clicking a template loads its query into the editor; **Run** executes the visible editable text. Show typed RDF terms, result columns/count, scoped model revision and concise errors/unready state. Provide Cancel, bounded result preview and safe CSV/JSON download where supported.
- Reset/cancel pending results on site/user/session change. Never show a late response for the previous tenant/site. An empty valid query result is allowed, but a missing model/failed query must not appear as an empty success.
- Add browser/component tests that click every template, edit the query, execute it, compare known answers, cancel, switch sites and exercise denied/expired auth. Never display credentials, internal paths or scanner/implementation details in the product flow.

### Rust API contract

Preserve current template routes/catalog compatibility. Add a clearly versioned read-only query endpoint, proposed **`POST /api/model/sparql/query`**, and extend **`GET /api/model/sparql/predefined`** with the curated text/result contract. UI and JWT-authenticated AI/MCP clients must call the **same** authorized central query service. Do not use the separate legacy edge prototype graph.

Request: query text and caller's building/site selection, optional requested preview bounds that the server clamps. Tenant/object/model scope is derived and validated by central. Response: stable schema, query/run id, exact scope and model/defs/query revision, typed SELECT rows or ASK boolean, row/byte counts, elapsed/status/diagnostics and explicit truncation/refusal. Keep an actual cancellation contract if execution is asynchronous. Cap query text and pending requests before costly staging.

Start with **read-only SELECT and ASK**. Add CONSTRUCT only if separately budgeted, authorized and needed. Parse with the locked SPARQL parser and inspect AST/algebra; reject UPDATE/LOAD/CLEAR/INSERT/DELETE, SERVICE/federation, caller-controlled remote datasets or file/network reads. Comments, strings, casing and nested subqueries must be handled by the parser, not keyword grep. If graph selectors are allowed, they can name only authorized in-memory graphs; client input cannot expand the server dataset.

Support editable joins/aggregates needed for useful engineering exploration within explicit resource limits. Enforce deadline, memory/materialization/row/byte/complexity/concurrency/spill limits and actual worker cancellation. `LIMIT` does not bound an aggregate/join before the result. A detached blocking worker with an HTTP timeout is unacceptable. Prefer version-tested interruptible execution, or a supervised Rust worker process with bounded snapshot/IPC and enforced supported resource limits that can be terminated and reaped. Avoid privileged containers or Docker-socket access. Declare unsupported query/resource cases and fail closed.

Required API negatives: anonymous/expired identity; foreign site/graph both directions; viewer mutation attempts; external SERVICE/FROM and UPDATE; parser ambiguity; large/slow join/path/regex/aggregate; output byte overflow; cancel/disconnect/shutdown; stale revision/late publication; concurrent tenants/cache; missing model. Paired valid queries must still pass, including literal/comment text resembling forbidden keywords. Isolated fixtures have independently known mechanical counts and topology. No live OT query may trigger a device read/write.

Document the read-only endpoint, Python/external AI client examples, template schema and query limits in canonical agent context and GH Pages. Query authors use standard Haystack terms and the documented minimal OpenFDD execution extensions; this API does not turn raw time series into RDF.

## P6 — CAMBER collaboration, independent AFDD/M&V checks and a stable external contract

Read private `CAMBER_REVIEW.md` and the focused handoff at `.cursor/agents/camber-interop-crosscheck-handoff-20261005.md`. This is external file/process collaboration, not a CAMBER product dependency or a new writable model authority. The draft reply is private at `YASSEN_REPLY_DRAFT.md`; no message has been sent.

Primary comparison sources:

- [CAMBER v0.99.1 release](https://github.com/yroussev/camber/releases/tag/v0.99.1), exact source `1d877ce9dddf2f568352aa69f3bfdeb93d38d892`, published 2026-10-03.
- [Tagged G36 harness](https://github.com/yroussev/camber/tree/v0.99.1/examples/openfdd_crosscheck): published OpenFDD rates are pinned to `32a6d4479abed81f9d6d0ff426260cc8ad8e30e2` / product 3.5.58 / PyPI 4.4.9, not current 3.5.65.
- [Tagged M&V vectors](https://github.com/yroussev/camber/tree/v0.99.1/examples/mv_vectors) and [interop proposal](https://github.com/yroussev/camber/blob/v0.99.1/docs/INTEROP-OPENFDD.md); [collaboration issue #22](https://github.com/yroussev/camber/issues/22).

### Rule tuning and per-equipment acceptance

Source review found these mechanisms remain at 215e159; rerun focused probes against the current/fixed source before publishing new detection rates:

1. `crates/fdd_rules/src/params.rs` inserts legacy defaults and overwrites explicit `EPS_SAT` from `SUPPLY_TOL`. Preserve documented explicit sensor tuning precedence and backwards-compatible aliases, rejecting conflicting configuration rather than silently replacing it.
2. FC9/11/14/15 consume a default shared `EPS_MAT` while their registry exposes sensor-specific parameters. The placeholder is resolved; the defect is disconnected effective tuning. Wire each intended measurement tolerance into the equation and test effective substituted SQL plus CLI/API config hashes. No unregistered shadow tuners.
3. SQL FC13 currently gates cooling strictly **>90%**, whereas pandas defaults to **>=1%**. A named G36 edition, equipment operating-state definition and independent equation expectation must determine the correction; agreement between two engines is not enough. Test 1%, 50%, exactly 90%, and full-open boundaries, signed coil behavior, fan heat, delays and justified sensor substitutions. Retain engine/profile/denominator labels.
4. CLI preflight checks table-wide roles; a neighbour's input must not make an incomplete equipment appear evaluated. Two AHUs in one building with different available mappings/finite telemetry must receive correct individual readiness and declined reasons. Test genuinely absent heating coils and invalid coil substitutes.
5. Treat minimum-OA as declared per-equipment commissioning evidence. Verify effective `econ_min_pos`/`oa_damper_econ_low` precedence and 5%/10% cases without changing every AHU to the LBNL fixture setting. No identifier or site hardcoding.

Fix actual Rust runtime rules and their documented external pandas twins; update both cookbooks and GH Pages with the chosen semantics, supported tuners, equation units, operating-state/denominator definitions and honest breaking-behavior notes. Runtime remains Rust; Python is only external agent/oracle tooling.

### Versioned external export: answer the five interop questions

Use one authorized native JSON/package export with a versioned schema/manifest and model revision; RDF stays a derived view. Proposed fields are a design to implement, not an already-supported contract:

1. Validated **site IANA timezone**, UTC timestamp encoding, display unit preference and explicit per-point kinds/units/source/status. Distinguish the site clock from a manifest stating timestamp UTC; do not assume Haystack `tz` abbreviations are IANA identifiers. Missing/ambiguous metadata requires an explicit user override with provenance.
2. Prefer stable package/bundle export with file/schema manifests, equipment type/topology and role maps. Physical Parquet directories, including tenant layouts and compaction generations, are internal/version-pinned unless explicitly promised. Build a consistent bounded read-only snapshot; never grant an external reader write access to the canonical writer.
3. Generate a supported alias/SQL-role crosswalk from the actual mapper. Unknown normalized headers are not canonical semantic roles. Generic water/pressure names need circuit context; numbered pumps need equipment identity. Preserve unsupported/ambiguous reasons.
4. Weather exports carry `equipType: weather` and an explicit points map. BAS outdoor-air sensors and external weather roles remain distinct; documented exact-header fallback is compatibility, not silent mapping authority.
5. Explicitly distinguish Boolean commands, numeric fractions and percentages, plus status versus command versus actual speed/position. A 1% signal must not become 100% through range guessing. Preserve any external-engine substitution as declared evidence, never as measured fan proof.

Roundtrip tests: two sites with different timezones/units; UTC instants around DST transitions; mixed point units; missing/conflicting legacy metadata; weather and BAS OAT together; duplicate/ambiguous roles; equivalent local identifiers across tenants; authorization; restart/model-revision consistency. Keep package JSON/ZIP backwards compatibility and report unknown metadata honestly.

### M&V comparison and independent engineering answers

Pin vector tag/schema/input/checker hashes and methods. Small synthetic vectors are appropriate for ordinary offline CI; rebuild real BDG2/LBNL data only in a separately budgeted, licensed/attributed job. Do not commit publisher datasets or casually download the approximately 330 MB BDG2 tier. The checker requires **NumPy and pandas**; it was not executed during this audit because the existing interpreter lacked NumPy. No CAMBER install is needed for consumers.

CAMBER-generated expected coefficients are comparison evidence. Add independent hand-derived arithmetic, prediction and savings answers so matching the comparator cannot be the only pass condition. The audit verified two useful 12-row, one-parameter examples against current G14 scoring: alternating 99/101 measured with prediction 100 has zero NMBE and R²=0; constant measured 100 with prediction 99 has NMBE 1.0909090909%. Both pass the current simulation gate but fail different parts of CAMBER's stated regression policy.

Keep **calibrated-simulation** and **regression-baseline** acceptance as separately named policies with purpose, source/edition, interval, parameter count, weighting, model selection, fit/holdout window and uncertainty assumptions. The vectors' R²/bias criteria are CAMBER policy, not a universal complete IPMVP Option C qualification requirement. Record fit-grid, BIC versus CVRMSE selection, heating-slope convention and deadband differences; do not force coefficients to match a different method. Test nonpositive/degenerate data, insufficient degrees of freedom, temperature extrapolation, partial periods and uncertainty before presenting qualified savings.

### Draft findings exchange

Review the versioned draft JSON as an external file adapter. Preserve engine/version, input/config/model/defs revisions, method, site timezone/window, evaluated and fault hours, denominator definition, status/reason, evidence/caveats and the native result. Unknown values remain unknown; `declined`/`not_evaluated` must never become `ok`. Reject incompatible major versions and invalid reports; keep independent engines' verdicts separate. External findings do not drive BAS writes. CAMBER can host its proposal while OpenFDD owns its adapter and contract tests; no extra shared repository is required now.

## P7 — tests, milestones, release and Grok closeout

For each bounded PR: smallest meaningful local tests for touched code on suitable capacity, then actual Actions gates; no low-RAM stack image builds. Fix tip failures rather than weakening assertions or ignoring new checks. Explicitly wire new resource, graph/runtime, Python adapter, evaluator and frontend suites into CI. Preserve SQL and pandas cookbooks and external Python tooling boundaries.

Every relevant finding has independent expected outcome, original failing evidence, fix SHA, test name, candidate identity and residual limitation. Update canonical docs/skills, HR evidence matrix, route/policy inventory, consumer matrix, bug ledger, SESSION_LOG and **MILESTONES.md** prospectively. Correct contradictory stale H9/H10/C1 claims and mark unmeasured performance honestly. Sync skills through the canonical installer; do not create a second vendor skill source.

At release, confirm latest VERSION and choose the next available tiny workspace patch (3.5.66 only if still next). Keep VERSION/Cargo/display/docs synchronized. Follow existing PR/merge authorization and release protocol; no self-created approval blockers. Verify master Actions, immutable GHCR digests/platforms and candidate smoke before deployment claims. Avoid modifying unrelated bot work or deleting branches not owned by this train.

Grok then owns the approved live window and issue closure. Provide exact affected gates and the repaired harness SHA, finite budgets, allowed origins/profile, nonempty tenant fixtures, expected output/receipt counts and resource observations. Run combined analytics/FDD/graph/import/compaction plus durable ingest/replay tests after the memory fixes. Record process starts/cgroup events/RSS/pool/materialization/spill/queue state, output correctness and cleanup. No new live stress is needed merely to demonstrate the old evaluator can lie.

**Issue closure rules:**

- #1127: implemented aggregate controls, real cancellation release, durable ingestion/replay, and combined candidate survival/correctness; missing historical kill metadata remains explicit.
- #1002/#1123/#997: actual authoritative model → SPARQL → typed bindings → real FDD/history/ECM plus independent semantic/compatibility tests; templates/plans alone cannot close it.
- #1003/#1004: robust required-set evaluator, measured declared performance, immutable candidate smoke/rollback/affected stress; skipped scale is PARTIAL.
- #999: actual app/role/object controls, repaired detector sabotage tests, complete applicable authenticated Python/ZAP/broker/profile evidence; licensed Nessus assessment remains BLOCKED until real scoped evidence exists.
- Header/Grok-generated issues: exact relevant response/plugin/candidate retest and documented scoped disposition, not blanket scanner suppression.

Append Grok/operator application findings to this train with links and acceptance; do not discard them because they were discovered after this audit. Stop closure if the candidate/harness differs, own controls fail, required checks disappear, cleanup fails or the evidence is incomplete. The objective is a corrected, reviewable next patch and honest acceptance, not more checked boxes.
