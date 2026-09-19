---
name: Wave S data model and graph review handoff
overview: Independent source audit and Cursor implementation prompt for vendor-neutral models, tenant isolation, JSON/Turtle exports, graph correctness, engineering capacities, Python ECM tools, GitHub Pages documentation, and measured optimization.
isProject: false
---

# Cursor prompt — finish the data model and graph contract

**Integrated (2026-09-19):** Master [`wave_s_master_ecb88a61.plan.md`](/home/ben/.cursor/plans/wave_s_master_ecb88a61.plan.md) owns this via child **S5** [`wave_s5_data_model_graph_ecm.plan.md`](wave_s5_data_model_graph_ecm.plan.md) + evidence [`wave_s_data_model_evidence.md`](wave_s_data_model_evidence.md). ADR/DM-06 start on **S2**; FQ for model/ECM gate only on **S4**. Order: S1→S2→S3→S5→S4. Do not duplicate S1 or launch another FQ MEGA for this handoff alone.

Continue the existing Wave S work in `/home/ben/Desktop/open-fdd`. Preserve work in progress; use one agent on bensbench. Follow the master’s authorized release sequence and stress windows.

The developer wants: vendor-neutral HVAC models; a non-admin client/vendor sees only authorized customer models; working JSON and Turtle exports; useful AI assistance; actual graph traversal with SPARQL; equipment schedule/design capacities usable by existing Python energy/ECM tools; a documented Open-FDD RDF extension where needed; and tests/measurements demonstrating correctness and performance. Update the online GitHub Pages documentation and agent instructions as part of implementation. Implement focused corrections and required regression coverage. Do not stop at an architectural essay, a graph visualization, or a generated TTL file.

## Evidence and boundaries of this review

Independent review on 2026-09-19 at source `471ef7ab5bdeaff6e0904c0cc032b252df3af675` (3.5.30, Wave S1). Cursor was actively working; recheck changed files before applying findings. Existing docs/pin lines may lag the source. No claim here about the currently deployed graph or live tenant leakage.

Three synthetic checks executed the actual TypeScript exporter with Node 24.21.0 and demonstrated three invariant failures. Reproducer:

```bash
node /home/ben/Documents/Codex/2026-09-16/cursor/outputs/openfdd-data-model-repro.mjs /home/ben/Desktop/open-fdd
```

Observed exit 1, all three cases failed. Exporter SHA-256 was `38fac5665733f0827e4ffc0aaa49802f2c58b86cb5a948c9a80f83c95bbf28b6`. This script checks identifiers and missing metadata, not complete RDF syntax or graph semantics. The review did not run a Rust build, RDF parser, live request, or performance benchmark. Other findings below are source observations requiring real integration regressions.

Read `AGENTS.md`, `openfdd_agent_spec/AGENTS.md`, the data-modeling and multi-tenant security skills, `docs/modeling/data-model-ttl.md`, `docs/modeling/package-schema.md`, `docs/agent/PACKAGE_AUTHORING.md`, `docs/mcp-agents/roles/package-mapping.md`, and the security audit/agent brief before editing. Observe the ban on heavy local Rust/container builds. CI or a prepared isolated environment owns those tests.

## 1. Settle what “one data model” means

Adopt one versioned semantic contract/vocabulary across vendors, with tenant-scoped instance models and explicit source adapters. A shared schema/ontology `.ttl` is reasonable. A single file containing every customer’s private instance data, loaded wholesale for each request, is not the default design.

Record an ADR covering:

- Shared vocabulary versus customer instance data. A model describes equipment, points, units, relationships, bindings, provenance and ownership. A `.ttl` file is a serialization; its presence does not prove an indexed, complete or secure graph.
- Vendor/manufacturer/protocol and tenant/customer are separate dimensions. One customer can use several vendors; a vendor service account can have explicit grants to several customers. Manufacturer names never confer access. Use authenticated membership and active tenant plus allowed site/object scope.
- One authoritative revision per tenant/site. Preserve current compact package maps/`columns.csv` and DataFusion FDD contracts while deriving validated graph views. Do not make JSON, TTL and a store independently writable authorities. An RDF-authoritative migration, if justified, needs its own migration/rollback contract; do not silently change ingest semantics.
- Keep telemetry and FDD mathematics in Parquet/DataFusion. Use indexed RDF/SPARQL for semantic relationships. Retain efficient typed lookups for simple keys; do not replace every dictionary lookup with SPARQL merely for appearance.
- Decide physical isolation: prefer separate tenant datasets/stores or demonstrably restricted query datasets; named graphs within them may organize sites/revisions. A named graph is not an ACL. Shared public ontology triples can be visible without exposing other tenants’ instances.
- Export one authorized site as TTL and existing application JSON. A dataset export that preserves named graph boundaries needs an appropriate dataset format such as TriG/N-Quads, with separate authorization; ordinary Turtle does not retain graph names. Application JSON is not automatically JSON-LD.

Do not force an unrelated ontology/database rewrite. Explain namespace/version choices and compatibility with the chosen Haystack vocabulary. Optional Brick mappings require explicit documented crosswalks; a prefix alone is not interoperability.

## 2. Reproduce and fix concrete findings

Priority denotes investigation/fix order, not a claim of a verified live exploit.

| ID | Priority / evidence | Required action and regression |
|---|---|---|
| DM-01 | P1, reproduced. `dataModelTurtle.ts::turtleIriSegment` maps both `AHU 1` and literal ID `enc_4148552031` to `enc_4148552031`. Rust `data_model_ttl.rs::iri_segment` uses the same algorithm. | Define an injective, versioned encoding or stable opaque resource identity. Reserve/escape the encoding prefix. Verify distinct inputs stay distinct in both exporters and any graph importer. Account for existing exported IDs in migration. |
| DM-02 | P1, reproduced. Building/equipment pairs `(X_equip_Y, Z)` and `(X, Y_equip_Z)` both emit `ofdd:building_X_equip_Y_equip_Z`. Subjects also lack tenant identity. | Use unambiguous tuple boundaries and tenant-aware identity. Test reserved separators, encoded strings, Unicode, repeated labels across tenants and graph merges. If duplicate building IDs are currently prohibited, enforce/test that explicitly rather than relying on undocumented global uniqueness. |
| DM-03 | P2, reproduced. TypeScript exporter exits the equipment loop early for zero mapped roles, dropping `unmapped_columns`; Rust emits them after its empty-role branch. | Preserve unmapped-only equipment metadata. Compare parsed Rust and TS graphs on the same fixtures; the existing substring tests missed this difference. |
| DM-04 | P1, source. `package.rs::get_package_mapping_handler` uses `infer_equipment_type_local` and `infer_parent_ahu`. IDs are searched for AHU/VAV/etc.; a single AHU sibling becomes the parent by default. The repo already has stamped-type helpers in `edge/src/equipment_types.rs`. | Honor explicit package/registry type and relationship metadata consistently. `AC_1` stamped `ahu` must not export as GENERAL. Guessed parent/type must be a reviewable proposal with provenance; never assert a guessed feeds edge as confirmed topology. Preserve unknown relationships without inventing them. |
| DM-05 | P1, source; tenant integration unverified. Central JSON/TTL handlers check building membership, but mapping storage helpers receive building/equipment only, read global `data/csv_buildings`, and consult shared session config. Legacy RDF persistence is global `data/model/haystack_grid.json` / `data_model.ttl`, with one process-wide store and no user argument. | Trace identity through handler, storage, exports and caches. Prove two tenants with identical labels cannot access or overwrite each other. Scope storage and cache keys explicitly or prove an enforced alternative. Do not expose the legacy global graph as a shared-tenant service. |
| DM-06 | P1, source. Product mapping TTL uses `urn:openfdd:ns#`; commissioning RDF uses `https://open-fdd.dev/model#` and different classes/predicates. SPARQL catalog queries the commissioning projection. Central router has no `/api/model/sparql` registration, while MCP advertises it and `edge/src/server.rs` implements it. | Produce a consumer/route matrix: SPA, central, legacy edge, MCP, graph store and exports. Query the actual product model revision when offering product graph tools. Add central graph capability only with scope/budget controls, or report legacy capability unavailable accurately until implemented. Never claim downloaded package TTL is already the MCP query dataset. |
| DM-07 | P2, source. `rdf.rs::turtle_local` replaces punctuation with `_`, collapsing distinct IDs; `term_to_binding_string` reverses `_` into `:` and flattens typed literals. `literal_object` tests floating point before integer. | Preserve exact IRIs and literal datatype/language; use standards-compliant result bindings or an explicitly versioned adapter. Test `site:a-b` vs `site:a_b`, large exact integers, booleans, strings and language tags. Do not return a changed identifier that agents may reuse in another API. |
| DM-08 | P2, source. `rdf.rs::sparql_select` has substring bans for INSERT/DELETE/LOAD/ADD/etc. Valid SELECT literals or variable names such as `?address` or `"load"` can be rejected. `query.rs` converts SPARQL errors to empty lists and can then return `ok:true`. | Enforce query type using a parser/algebra allowlist before evaluation, propagate real errors, and test valid words/comments/IRIs containing those substrings. Never turn parse/store/query failure into “no equipment.” |
| DM-09 | P2, source. `with_store` reloads/parses/serializes/hashes the whole Haystack grid even on a cache hit; rebuild serializes TTL then reparses it under a write lock. `sparql_select` collects all solutions before `MAX_ROWS=5000` truncation in `sparql.rs`. `sampling_health` reads and scans each full CSV during mapping inventory requests. | Benchmark first, then bound query execution/materialization and cache immutable model revisions/statistics. A final row limit or HTTP timeout alone does not bound query CPU/RAM. Avoid repeated telemetry scans for a metadata/export view. |
| DM-10 | P2, source. Legacy RDF invents a sensor marker when no role marker exists, treats marker presence as type evidence, and uses unversioned/custom Haystack-looking terms. Package TTL omits JSON unit/validation/provenance fields. | Define required graph content and a versioned projection/crosswalk. Separate valid RDF syntax, complete domain semantics, vocabulary conformance and FDD readiness. Test false markers and unknown/missing units; never claim full Haystack/Brick equivalence or lossless JSON↔TTL round-trip without evidence. |

Additional cases to inspect: `query.rs::source_coverage` binds protocol before its OPTIONAL source bindings; verify expected protocol counts using actual SPARQL fixtures. `network_graph` checks the destination equipment of a feed but can retain an out-of-scope source; require both endpoints and their metadata to be authorized. `scope.rs` falls back to active/first site or equipment; missing scope must not silently choose a private tenant object. All are legacy-path observations until deployment reachability is established.

## 3. Secure the full model lifecycle

Use hub admin, A/B operators, A viewer, A scoped agent and a multi-customer vendor account with explicit grants. Include identical equipment/point/building labels with different canaries and a revoked/removed grant.

- Own-site list/read/edit/export/query succeeds according to role; A→B and B→A fail without disclosing labels, counts, graph names, errors or source paths. Viewer reads its model but cannot change it. Vendor access follows granted tenants only. Validate identity and positive own-data controls before accepting a denial.
- Cover package model JSON/TTL, mapping edits, session/role config, cached exports, query catalogs/results, model/commissioning endpoints, download jobs/URLs and MCP wrappers. Preserve full-site export even when the UI editor filters one equipment item; document any deliberately filtered API separately.
- Authorize the dataset before evaluating SPARQL. Test `GRAPH ?g`, named/default graph selection, FROM/FROM NAMED, nested SELECT, UNION, OPTIONAL, aggregates and property paths; filtering only final rows is insufficient. Shared inference/materialization must not create cross-tenant derived edges.
- Reject unsupported query forms and arbitrary remote access before evaluation. Verify SERVICE (including SILENT/variable targets), external graph loading and update operations against the pinned engine/features. Current lockfile uses Oxigraph 0.5.9; do not infer its compiled network behavior from newer documentation. No live egress probing is needed: use an isolated counting sink and expect zero requests.
- Scope caches/ETags/export artifacts to authorization scope plus tenant/site/model/schema revision. Test out-of-order responses during site/tenant/account switching and permission revocation. The Mapping page currently checks building ID for export source; verify the complete identity/tenant lifecycle, including identical building IDs and pending requests.
- Model updates are validated, atomic and revisioned; a failed import leaves the prior good model intact and returns a failure. Readers observe complete old or new snapshots. Detect concurrent updates with an expected revision; invalidate projections/caches after successful commit. Keep backup/restore and tenant deletion semantics explicit.

## 4. Preserve JSON exports and make AI tools dependable

Maintain current JSON download/view behavior and compact package authoring. JSON, Turtle and SPARQL must agree on their declared shared fields for the same authorized revision: equipment, point bindings, explicit type/parent relationships and unmapped state. Publish a field crosswalk stating any deliberate RDF omissions. Add unit/provenance/validation metadata where required by the adopted graph contract. Do not erase useful JSON fields merely to make parity tests pass.

Use one canonical server projection for online consumers, or prove parity between separately maintained TS/Rust emitters. Compare RDF graphs by triples/isomorphism, not output ordering or blank-node names. Keep timestamps separate from deterministic model content/revision hashes.

External AI agents should have scoped tools to inspect the model, retrieve query templates, resolve identifiers/relationships, preview a proposed mapping diff and apply an authorized validated revision. Read tools never need hub-admin credentials. Mutations retain existing role/confirm controls. Keep model labels/vendor text as untrusted data, not instructions that can alter scope or execute commands.

AI suggestions carry source evidence, confidence/unknown state and review status. A vendor alias adapter maps explicit source headers/units/protocol references into the canonical contract; it must not invent a sensor, unit conversion, parent AHU or point role to make FDD pass. An opaque equipment label cannot erase a stamped type.

`docs/mcp-agents/roles/package-mapping.md` explicitly labels richer mapping tools SCAFFOLD. Audit actual tool discovery and calls against central. Implement a scoped capability or mark it unavailable; do not pretend a documented future tool is shipped. Provide an executable capability smoke test for advertised graph/model tools, content type and auth behavior.

## 5. Use actual graph queries and validate semantics

Do not implement graph answers, graph authorization, or SPARQL classification with raw TTL text scanning, regex or grep. Repository text searches are fine for development; typed maps and semantic indexes are fine for exact lookups. Production relationship answers need structured model edges and the chosen graph engine.

Create a small versioned vocabulary/shape set with documented classes, relationships, units, external identifiers, provenance and revision rules. Use the chosen Haystack RDF mapping accurately or explicitly label Open-FDD-specific terms; pin vocabulary versions. Validate with SHACL or equivalently explicit graph constraints in tooling/CI, with separately labeled syntax/schema/domain/FDD-readiness results.

Fixtures must include multiple manufacturers/protocols in one tenant, the same manufacturer across tenants, explicit versus unknown parent relationships, malformed/dangling references, duplicate IDs, Unicode/quotes/backslashes/trailing-dot IDs, unlabeled points, false markers, duplicate/ambiguous roles, and unit incompatibility. Only enforce cycles/cardinalities forbidden by a specific domain relation; do not blanket-forbid all graph cycles.

Run parser tests against both actual emitted TTL implementations. Do not “prove valid Turtle” with `contains("@prefix")`. Require graph equality for the declared projection, exact identity preservation, and deterministic exports modulo ordering/blank nodes. Cover the three reproduced exporter failures with permanent regressions, plus a corpus of adversarial identifier tuples.

Run real SPARQL assertions: point→equipment→site, explicit AHU→VAV paths, inverse relationships, missing bindings with OPTIONAL, protocol counts, filters on typed units/values, and tenant-scoped aggregates. Include successful zero-result queries separately from syntax/store/deadline failures. SQL role maps must agree with graph bindings and continue producing the existing expected FDD results on the same package fixture.

## 6. Measure optimization instead of assuming it

Start with existing Oxigraph and canonical mapping helpers; introduce another database/service only if measured requirements justify it. Choose fixture cardinalities representative of expected deployments, e.g. 1k/10k/100k points with multiple sites/tenants and fixed seeded topology; run larger workloads in CI or a suitable isolated host.

Record candidate/harness/schema versions, hardware and limits, triples/equipment/point counts, and expected answers. Measure separately: metadata I/O, sampling scans, graph construction, cold/warm queries, export serialization, update-to-query freshness, p50/p95 latency, peak RSS, bytes read, rebuild count, and concurrent read/update lock contention. Include scoped list, adjacency, multi-hop, aggregate and JSON/TTL export workloads at stated bounded concurrency. Keep model metadata performance separate from telemetry SQL performance.

Investigate immutable snapshots keyed by tenant/site/model revision, revision-triggered rebuild/incremental updates, shared read-only vocabulary, prepared query templates, streaming result caps, bounded worker queues, real cancellation, and a bounded tenant-cache eviction policy. Cache import-time sampling statistics against the telemetry revision instead of rescanning full CSVs per inventory request; validate ordering assumptions for first/last timestamps. Avoid holding a global exclusive lock for an entire long query when an immutable snapshot can safely serve readers.

Define budgets before evaluating success and show baseline→candidate measurements with identical datasets/queries and correct answers. A row LIMIT can still require expensive joins/sorts/aggregates; prove cancellation stops backend work and memory stays bounded. No “optimized” claim without measurements, and no lower latency achieved by dropping metadata, relationships or authorization checks.

## 7. Add engineering quantities and connect them to existing ECM tools

The developer explicitly authorizes Open-FDD-specific RDF vocabulary for engineering capacities and related metadata. Define RDF classes/properties and their semantics in an Open-FDD namespace; these are model terms, while `?capacity` in SPARQL is a query variable. Reuse a standard term only when its definition actually matches. Do not mint Open-FDD properties inside the Haystack or Brick namespace or claim those projects endorse the extensions.

Read `openfdd_agent_spec/skills/openfdd-ecm-engineering/SKILL.md`, `openfdd_agent_spec/skills/openfdd-pypi-oracle/SKILL.md`, `docs/ecm/agent-context.md`, `docs/ecm/engineering-calcs.md`, and their relevant handoffs. Reconcile this work with Wave S2's agent contract and S3's PyPI/M&V work. Agree on one contract and its dependencies; do not independently re-port existing calculators.

### 7.1 Define a small versioned vocabulary with typed quantities

Publish a vocabulary `.ttl`, executable validation shapes/constraints, and JSON schema/crosswalk. Choose the canonical namespace in the ADR in section 1, accounting for the two existing namespaces and exported identifiers. Maintain stable meaning for published IRIs, explicit schema versions, and migration/deprecation rules. Tenant equipment/evidence instances use separate stable identities; the public vocabulary contains no private equipment data.

Start with the following proposed Open-FDD properties. Final names can change before the contract is frozen; implement and document each supported term consistently. Each capacity/flow/power/efficiency property links to a quantity/evidence record, rather than a naked ambiguous number.

| Proposed property or relation | Meaning and required context |
|---|---|
| `ofdd:ratedCoolingCapacity` | Thermal output at identified rating conditions; specify total versus sensible and cooling mode. |
| `ofdd:ratedHeatingCapacity` | Thermal output, with heating mode, equipment boundary and rating conditions. |
| `ofdd:ratedFuelInputPower` | Fuel input rate; record fuel and HHV/LHV basis where relevant. |
| `ofdd:ratedElectricalInputPower` | Electrical input at an identified boundary and operating/rating point. |
| `ofdd:ratedShaftPower` | Mechanical shaft output; separate from measured electrical input. |
| `ofdd:designSupplyAirflow`, `ofdd:designOutdoorAirflow` | Design volume flow and its reference conditions; preserve design and measured/TAB values independently. |
| `ofdd:designWaterFlow` | Flow with fluid, loop/component and operating condition references. |
| `ofdd:designExternalStaticPressure`, `ofdd:designPumpHead` | State pressure measurement boundary or head/fluid basis; do not equate pressure and head without an explicit conversion. |
| `ofdd:ratedCOP`, `ofdd:ratedEER`, `ofdd:ratedThermalEfficiency` | Distinct efficiency metrics, conditions and applicable energy basis; seasonal metrics need distinct definitions. |
| `ofdd:hasPerformanceCurve` | Versioned performance map with independent variables, units, source, interpolation method and valid domain. |
| `ofdd:hasComponent`, `ofdd:hasOperatingSchedule` | Installed system/component relationships and time-based operating schedules; avoid counting AHU and component capacities twice. |

A quantity record must define numeric value, registered unit, quantity kind, design/rated/TAB/measured/assumed basis, source type, source reference, source revision/date, rating conditions when applicable, validity/review status and confidence. Record document page/table/row or equipment schedule cell when available. Preserve original value/unit and any normalized value/conversion trace. An authorized evidence identifier is preferable to embedding local paths or bearer download URLs.

For optional context, represent absence explicitly; do not require fabricated dates or rating temperatures just to accept a legacy inventory. A partial model can be valid inventory while unready for a particular calculation. Separate confidence, human approval and completeness; confidence is not a validation result. Preserve multiple conflicting sources as separate records, with an explicit selection/review policy and reproducible selected record IDs. Do not average ratings from different conditions or choose one arbitrarily.

Illustrative syntax only, with synthetic values and the current package namespace; the final namespace, unit registry and full constraints belong in the ADR and committed fixtures:

```turtle
@prefix ofdd: <urn:openfdd:ns#> .
@prefix ex: <urn:openfdd:example:tenant-a:> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

ex:ahu-01 a ofdd:Equipment ;
    ofdd:ratedCoolingCapacity ex:ahu-01-cooling-design-01 .

ex:ahu-01-cooling-design-01 a ofdd:EngineeringQuantity ;
    ofdd:numericValue "120.0"^^xsd:decimal ;
    ofdd:unitCode "kW" ;
    ofdd:quantityKind ofdd:ThermalPower ;
    ofdd:valueBasis ofdd:Design ;
    ofdd:sourceType "design_document" ;
    ofdd:sourceReference ex:mechanical-schedule-rev-a ;
    ofdd:sourceLocator "M-601 / AHU-01 / total cooling" ;
    ofdd:reviewStatus ofdd:NeedsReview .
```

This example is incomplete for an annual-savings calculation: no load profile, operating hours, selected rating conditions or proposed measure has been provided. The agent must surface those missing inputs. It must never treat `120 kW` thermal capacity as measured electrical demand or multiply it by assumed annual hours without a declared supported method and assumptions.

Keep mechanical equipment schedules (design documents) distinct from operating calendars. Calendar data needs timezone, weekday/holiday exceptions, valid date range and DST behavior when deriving hours. Define per-unit versus bank-total capacity, installed quantity, duty/standby/staging relationships, and heating/cooling modes before aggregation. Preserve site/plant/physical equipment boundaries and BAS point/meter bindings. Time-series samples remain in the historian; the model carries authorized references, periods and derived-value provenance.

### 7.2 Persist the contract through the real application

Trace import → validated storage → model revision → JSON/TTL → query dataset → engineering bundle → external tool. Extend the actual package importer, metadata persistence and exporters together, with backward-compatible schema negotiation. Adding fields to a JSON example is insufficient if the importer silently drops them or interprets them as point mappings. Unsupported fields/versions need an explicit outcome. Prove save/reload/re-export retains engineering values, units and evidence, including equipment without mapped BAS points.

Provide an authorized way to review/edit these quantities and inspect their sources through the existing model workflow/API. Extracted schedule/OCR values remain proposals until reviewed; evidence document contents are untrusted input. Keep source documents, graph nodes, model snapshots, exports and derived calculation results under the same tenant/object authorization. AI agents must receive their scoped model and evidence without needing admin credentials. Add tests for unauthorized source-document retrieval and derived-result access, not only graph queries.

### 7.3 Build a typed adapter into existing Python math

Use `open_fdd.ecm_engineering.calculate`, its registry, `ECMJob`, `EngineeringInput`, `SourceType`, `AssumptionMethod`, `EvidenceValue`, `ProvenanceClass`, `MeasureResultMeta` and calculation traces as the starting point. Specify an explicit mapping between model quantities and these contracts; do not create competing provenance enums with unclear conversions. Current `EngineeringInput.unit` is a string and its validators primarily check evidence conventions. A unit string alone does not validate dimensional compatibility or calculation readiness.

Implement discoverable, scoped external tools to retrieve engineering inputs, report missing/conflicting inputs for a named method, preview baseline/proposed scenarios, and run an allowed registered calculator with validated arguments. Names and request schemas must be documented and exercised against actual tool discovery. Keep Python outside the product HTTP request path, as required by repo architecture. `agent_cli.py` currently calls itself Stage-1 stubs and its proposed updates return `persisted:false`, even on the apply path; do not present that as a shipped editing mechanism.

The adapter must validate finite numbers, expected dimensions, registered units, method-specific bounds, selected source/conditions, time coverage and calculation boundary before calling math. Audit optional defaults as well as required values: `_req` already rejects non-finite required values, while some optional floats and negative-hour clamping need explicit qualification at the contract boundary. Missing/invalid inputs return structured issues and no savings result. Clearly defined defaults may remain only as visible method assumptions. Preserve valid negative savings when a proposal increases use. Do not impose a universal 0–1 bound on COP or all efficiency conventions; validation depends on the metric and basis.

At minimum integrate and test these existing methods end to end:

- `fan_affinity`: reference electrical power at the method's stated speed, speed fractions, hours and explicit power-curve assumptions. Motor nameplate horsepower alone is insufficient to establish electrical load; identify required efficiencies/loading evidence or report the missing inputs.
- `schedule_reduction`: equipment electrical power with its operating basis, baseline/proposed hours and a supported average-load assumption. Distinguish configured schedule hours from measured run hours and avoid applying a load fraction twice to already averaged power.
- `kw_per_ton_improvement` or `boiler_efficiency_improvement`: derive annual ton-hours or useful heating demand from referenced evidence and a documented method. Nameplate capacity alone cannot establish annual load. Keep useful heat and fuel input distinct, and align efficiency rating/energy bases.

Unit tests must cover thermal versus electrical kW (same physical dimension, different meaning), kW versus kWh, refrigeration tons versus mass, Btu/h versus energy, shaft hp versus electrical kW, CFM versus SI flow, absolute temperature versus temperature difference, and percent versus fraction. Use pinned conversion definitions and explicit tolerances. Check physical feasibility against each method's documented validity region without silently changing invalid values into plausible ones.

Baseline and proposed cases are immutable snapshots/scenario overlays with separate IDs, rather than edits to the installed equipment truth. A result records model/telemetry/evidence revisions, selected quantity IDs, calculator and wheel version, input units/conversions, time/weather period, scope/allocation, assumptions, warnings and calculation trace. Preserve non-additive/interaction metadata when combining ECMs. Mark reverse-solved EnergyPlus inputs FITTED according to the existing ECM guide; matching a fitted result is not independent validation. Monetary results additionally require an explicit tariff/cost source and period; do not invent those inputs.

Acceptance fixtures: at least two vendors and two tenants with repeated labels; a documented AHU fan case; a schedule reduction case with calendar exceptions; and a cooling or boiler case. Require real RDF parsing/query → typed adapter → actual Python calculator → trace/JSON export tests, independent expected arithmetic, a capacity-only missing-input case, invalid/conflicting units, unauthorized evidence access, and a changed model revision invalidating stale results. Run relevant installed-wheel tests if public PyPI interfaces change, coordinated with S3. Keep these deterministic checks in CI and the appropriate qualification profile; additional live stress is governed by the master.

## 8. Ship usable GitHub Pages and agent documentation

Documentation is part of completion. Add/update public source under `docs/` and use the existing `.github/workflows/docs-pages.yml` workflow. Proposed page locations are `docs/modeling/engineering-quantities.md`, `docs/modeling/rdf-vocabulary.md`, and `docs/ecm/model-to-calculations.md`; reuse equivalent existing pages if present. Add downloadable versioned vocabulary, shapes/schema, a synthetic JSON/TTL fixture and runnable query/calculator examples in documented asset locations. Keep one authoritative vocabulary source and generate/copy published assets with a parity check to prevent drift.

Required content:

1. Plain-language explanation of shared vocabulary, private tenant models, design capacities, measured inputs and ECM readiness.
2. Term reference for every new class/property: exact IRI, definition, subject/object types, cardinality, quantity kind/allowed units, conditions, provenance, examples, version introduced and deprecation policy. Explain Open-FDD extensions and any verified standard crosswalks.
3. Mechanical schedule onboarding walkthrough: identify equipment, enter/import reviewed values with document locators, resolve conflicts, validate, save a revision, export JSON/TTL and query it. Show what happens with missing capacities or unknown operating conditions.
4. Agent walkthrough using actual shipped discovery/auth schemas: obtain only authorized inputs, select a registered calculation, inspect missing inputs, run a synthetic baseline/proposal and inspect trace/assumptions. Include exact tested commands and expected output. Keep credentials out of examples.
5. Migration/compatibility notes for existing mappings, namespaces, units, exports and clients; document actual supported features and unavailable scaffolds accurately.

Wire navigation and cross-links from `docs/modeling/index.md`, `docs/modeling/data-model-ttl.md`, `docs/modeling/package-schema.md`, `docs/ecm/engineering-calcs.md` and `docs/ecm/agent-context.md`. Current modeling parent title is `Haystack Modeling`; `data-model-ttl.md` currently says `parent: Modeling`. Resolve that mismatch and verify the rendered sidebar. Preserve existing public permalinks or add a supported redirect; account for `baseurl: /open-fdd`. Update the data-modeling/ECM skills and capability ledger to describe implemented behavior.

Run the workflow's `bundle exec jekyll build --trace --strict_front_matter` from `docs` in CI or the suitable docs environment. Check rendered new pages, sidebar/search discoverability, internal links, downloadable asset existence, and syntax/execution of examples. The current workflow only checks index and quick-start output; add focused checks for the new documentation/assets. A generated Markdown file alone is not proof of a successful online docs update. After the authorized merge/deployment, record the successful Pages deployment and verify the resulting public URLs; if not yet deployed, report that explicitly. Keep private audit findings, tenant fixtures and deployment details out of public tutorial material; use synthetic examples and the repo's private vulnerability reporting policy.

## 9. Integrate model, ECM and security checks into stress testing

The developer explicitly requests stress testing as part of this work. Extend the saved qualification tooling and its evaluated checks. Each applicable scheduled stress run must include the implemented model/ECM checks and report its coverage; the checks must not exist only as a one-off notebook or disconnected report. Model fidelity, calculator correctness, tenant authorization and performance each have distinct assertions and verdicts.

Use the existing integration points: `scripts/nightly-ot-bench/run_railway_hub_stress.sh`, `25_security_python_harness.sh`, `25b_security_post_stress.sh`, `scripts/security/openfdd_security/`, `scripts/security/inventory/`, its profile/report schemas, and `scripts/qualification/write_manifest.py`. Inspect current gate allocation before adding IDs. Keep X/Y/Z security suites authoritative for their existing controls; add model/ECM checks and route dispositions without falsely marking reserved PLANNED checks implemented.

| Layer | Required coverage | Execution placement |
|---|---|---|
| Deterministic regression | RDF identity/parity, graph semantics, quantity persistence, units, missing/conflicting inputs, independent ECM arithmetic, source and result authorization, detector evaluation | CI on relevant changes, including installed-wheel checks when applicable. |
| Bounded model/ECM qualification | Fixture preflight, own/foreign tenant controls, JSON/TTL/SPARQL consistency, scoped evidence retrieval, graph-to-calculator trace and expected result, post-run revision/identity checks | A reusable gate referenced by each applicable stress profile; online reads and external Python calculation where supported. |
| Concurrency and fault load | Simultaneous A/B reads, graph traversals, export jobs, model updates, calculator requests and grant changes; lock/rebuild/cancellation/rollback behavior | Disposable isolated fixture environment with explicit rate/concurrency/size/deadline budgets. Mutations target those fixtures. |
| Railway FQ integration | Existing authentication/security gates plus bounded supported model/ECM pre/post checks, with matching candidate and evidence links | The master currently permits full Railway MEGA only after S1 and S4; S2/S3 remain smoke. Integrate new checks into S4 if delivered by then. |

Do not retroactively attach new checks to an earlier completed pin's result. If implementation needs a follow-up child beyond S4, add its dependency and explicit qualification window to the master before execution; preserve one child/PR at a time. This handoff requests tooling and integrated testing, not an immediate live load run while Cursor is changing the candidate.

Define the fixture manifest and pass criteria before running:

- Seed reproducible tenant A/B/admin/viewer/agent/vendor identities, repeated equipment labels, source documents and expected capacities/relationships. Record authenticated identity, granted scope, source/model revision, expected graph answers and independently established calculation results. A valid own-object success control precedes foreign-object denial assertions.
- Mix reads and updates across tenants. Concurrent JSON/TTL/query/calculation results must identify complete committed snapshots; no partial model, mixed revision, stale revoked grant, lost update or cross-tenant cache reuse is acceptable. A legitimate revision-conflict response is distinct from corruption. Validate scenario/result isolation and no duplicate aggregation of shared equipment/components.
- Bound request count, rate, concurrency, input/triple/result sizes, elapsed time and memory. Apply per-query and per-calculation cancellation. Prove timed-out work stops and a later small valid request completes. Monitor telemetry ingest/FDD health during approved integration load; metadata testing must not quietly starve the rest of the application.
- Capture pre/during/post latency and resource measurements from section 6, semantic results, model revisions and remaining background work. Restore/clean only disposable fixture objects and verify postchecks after both successful and failed runs. Postchecks cannot erase a precheck, load or correctness failure.
- Evaluate the evaluators: intentionally broken local fixtures must expose tenant leaks, missing capacity/unit conversion, altered expected graph edges, wrong calculator output, stale cache/revision, skipped checks and timeouts. Require each detector to fail for its intended defect and pass for a corrected fixture. Test orchestration/report tampering and nonzero exit propagation alongside existing `tests/security/test_broken_fixtures.py`, `test_orchestrator_sabotage.py` and qualification tests. A test that only asserts HTTP 200 or matches the implementation's own incorrect output is insufficient.

**Concrete reporting gap to reproduce and correct:** in the reviewed `25b_security_post_stress.sh`, the postcheck predicate requires `counts.planned > 0`, excludes only overall FAIL/ERROR, and checks zero failures. It does not require nonzero passed/implemented checks or reject overall BLOCKED/N/A. A blocked/all-unexecuted report can therefore satisfy that predicate. Add a fixture demonstrating this and route pre/post verdicts through consistent report validation that verifies required check IDs actually executed with acceptable results. A partial postcheck need not pretend to be a full profile, but its required subset must be explicitly defined and satisfied.

Extend the evidence manifest with candidate commit/image digest, harness and wheel versions, schema/profile/check IDs, fixture/model revisions, budgets, expected/actual summaries, artifact hashes, start/end timestamps and per-layer PASS/FAIL/BLOCKED/justified N/A. Reject stale artifacts, profile mismatches, omitted required checks, dry-run-only output, zero/all-skipped check sets, unexpected 5xx/timeouts and missing result bodies. Missing live graph capability must be reported unavailable and leave that required coverage incomplete; do not pass it because a fallback returned an empty list. Keep secret/environment values out of reports.

Report exact tested scope and residual limitations. Passing bounded stress and named security controls provides reproducible evidence for that candidate/configuration; it cannot prove the absence of every security vulnerability. Documentation and completion language must preserve that distinction.

## 10. Completion and integration with Wave S

Implement in focused changes coordinated with the active master. Follow its existing release authority; this review does not itself request additional deployment, OT writes or live benchmarks. Do not alter real customer models to create test fixtures.

- [ ] ADR and consumer/route matrix explain source of truth, vendor/tenant separation, model revisions, query backend and export scope.
- [ ] DM-01 through DM-10 have a disposition, source trace and applicable regression evidence. Confirmed defects have focused fixes; unresolved concerns remain visible.
- [ ] Parsed Rust/TS RDF parity, multi-vendor metadata, actual SPARQL semantics and tenant/role tests pass on isolated fixtures.
- [ ] Full-site JSON/TTL UI exports and actual MCP capabilities pass integration tests, including stale-response/revocation cases.
- [ ] Benchmark table establishes baseline, budgets and measured candidate results, with correctness unchanged.
- [ ] Versioned Open-FDD engineering vocabulary, typed unit/evidence contract and importer/exporter persistence support reviewed mechanical schedule data without affecting existing point mappings.
- [ ] Scoped model-to-Python ECM tools pass the end-to-end cases, missing-input/unit/tenant checks and reproducible calculation-trace requirements in section 7.
- [ ] Public GitHub Pages vocabulary/onboarding/agent examples build, link and execute correctly; publication status and tested feature versions are recorded.
- [ ] Model checks integrate with the existing security/qualification schema and appropriate Wave S CI gates. A missing fixture, skipped parser test or unavailable graph route cannot produce full model qualification.
- [ ] The evaluated model/ECM stress gate is wired into applicable profiles, pre/post evidence validation rejects unexecuted/blocked required checks, and the authorized FQ window includes the new coverage on its exact candidate.
- [ ] Graph failures, corruption, empty scope, duplicate identifiers and resource exhaustion are deliberately injected to demonstrate the tests detect them.
- [ ] Documentation/skills/session log describe shipped behavior; reports distinguish code inspection, executed tests, CI evidence and live verification.

Deliver an evidence table: requirement → implementation/symbol → test/command → candidate/model revision → artifact → PASS/FAIL/BLOCKED or justified N/A. Conclude with the exact model/query/export scope supported and any remaining limitation. A security stress PASS alone does not establish model fidelity or graph optimization.

## Primary references for design decisions

- [W3C RDF concepts and datasets](https://www.w3.org/TR/rdf11-concepts/) — graph/dataset structure and global IRI identity; these do not supply application authorization.
- [Project Haystack RDF mapping](https://project-haystack.org/doc/docHaystack/Rdf) — vocabulary namespaces and mapping rules; compare actual emitted terms before claiming conformance.
- [W3C SPARQL JSON results](https://www.w3.org/TR/sparql11-results-json/) — preserve IRI/literal identity and datatype/language in query results.
- [W3C SHACL](https://www.w3.org/TR/shacl/) — graph validation and explicit conformance results.
- [Oxigraph evaluator documentation](https://docs.rs/oxigraph/latest/oxigraph/sparql/struct.SparqlEvaluator.html) — consult the pinned local version/API/features before implementation; the latest docs may differ from 0.5.9.

These are design references, not evidence that this application has passed any of the required checks.
