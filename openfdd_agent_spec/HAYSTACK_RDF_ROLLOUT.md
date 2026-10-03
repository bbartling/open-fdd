# Haystack RDF rollout requirements

**Status: implementation requirements, not a shipped capability claim.**
Recorded 2026-09-22 against source `4eb20a0d6c9ce5d3e831d9fa54247d31abfa567c`.
Recheck the current source and deployment before planning or changing status.
The developer wants Haystack RDF interoperability, readable model views, and
continued ZIP/JSON ingestion, with permanent tests and evaluated stress gates.

The Cursor planning entry point is
[haystack-rdf-implementation-handoff.md](../.cursor/agents/haystack-rdf-implementation-handoff.md).
This file carries the portable requirements even when local Cursor plans are
absent. Reconcile with the existing S5/V5 work and
[graph ADR](../docs/architecture/ADR_data_model_graph.md); the active release
master owns scheduling. This document does not close existing model/ECM items.

**Executable plans (2026-09-24):** master
[`.cursor/plans/wave_haystack_rdf_master.plan.md`](../.cursor/plans/wave_haystack_rdf_master.plan.md)
and children C1–C6; GitHub tracking [#997](https://github.com/bbartling/open-fdd/issues/997)
(+ #998, #1000–#1004). Implementation starts when that plan is run — not from
reading this requirements file alone.

## Standards and the compatibility claim

Read the primary specifications and record the selected library versions:

- [Haystack RDF](https://project-haystack.org/doc/docHaystack/Rdf)
- [Haystack JSON](https://project-haystack.org/doc/docHaystack/Json)
- [Point modeling](https://project-haystack.org/doc/docHaystack/Points)
- [Equipment modeling](https://project-haystack.org/doc/docHaystack/Equips)

Define a named, versioned compatibility profile. Separate RDF syntax validity,
Haystack semantics, completeness of a site's mapping, FDD readiness, engineering
calculation readiness, and availability of graph/API services. Passing one does
not establish the others. Export support alone does not establish a complete
Haystack HTTP server or certification.

Use the actual library base URIs and versions for defs. Follow the documented
instance mapping: classes, marker tags through `ph:hasTag`, typed values, and
references to instance blank nodes. Maintain stable internal identities and an
explicit export mapping; blank-node labels are not persistent global IDs.
An internal named-IRI graph is permitted, but document its projection into the
selected interchange profile. Never manufacture a Haystack def from an SQL role
or infer its namespace by splitting a column name.

The RDF page leaves units attached to numeric instance values and some relation
semantics as pending work. Distinguish those quantities from a point's defined
`unit` metadata. Document the chosen extension and its limits. Unknown tags
without defs are excluded from the strict Haystack projection with an explicit
projection report; retain the source information in native metadata. Define
Open-FDD extension terms in the Open-FDD namespace, with documented semantics
and defs where required by the profile. Never mint them inside Haystack/Brick.

## Architecture and compatibility requirements

1. **Preserve package ingestion.** Existing `openfdd_package_v1` ZIPs and compact
   JSON maps remain accepted. Add versioned semantic metadata without changing
   the meaning of old fields or requiring fabricated metadata for old packages.
   Trace the actual importer before choosing a sidecar name or schema.
2. **One authority per tenant/site revision.** Extend persisted native metadata
   and derive exports/query datasets from it. Do not create independently writable
   JSON, Turtle, and graph copies. Specify revision ownership, concurrent-edit
   conflict handling, deletion, cache invalidation, and atomic import failure.
3. **Real entities.** Preserve site/equipment/point IDs, display labels, tags,
   typed values, units, source bindings, provenance, and confirmed relationships.
   Equipment references its site; points reference their site and equipment and
   carry the applicable function/kind/unit information. Tag optional capabilities
   only when supported. Model containment and supply relationships separately.
4. **Preserve uncertainty.** Unknown units, missing topology, duplicate role
   candidates, and inferred relationships stay explicit. Multiple similar sensors
   may be valid Haystack entities while still needing an FDD selection policy.
   Do not select the first column or promote a guessed relationship to a fact
   merely to obtain a passing readiness result. Unmapped columns need not all
   become FDD inputs; distinguish intentional exclusions from unresolved mapping.
5. **Keep the runtime boundaries.** Telemetry and FDD remain Parquet/DataFusion.
   Rust owns product ingestion/APIs/serialization. Python remains external
   engineering/agent/CI tooling. Use structured model edges and real RDF queries
   for graph semantics; repository grep is fine for development, not graph answers.
6. **Make identity and access explicit.** Vendor and tenant are independent.
   Repeated labels/IDs across tenants must not collide when exports are combined.
   Server-derived scope governs storage, caches, queries, downloads, jobs and MCP.
   A named graph or a client-supplied tenant ID is not authorization.
7. **Keep export contracts explicit.** The existing `openfdd_data_model_v1`
   download is an inventory view, not automatically a ZIP input or Haystack JSON.
   Publish a field crosswalk and supported import/export directions. Preserve
   supported semantic metadata through import, persistence, restart and export.
   Decide whether to add Haystack JSON interchange; test every direction advertised.
   Never describe an intentionally lossy strict projection as a full round trip.
8. **Centralize serialization.** Prefer an authorized backend export consumed by
   the SPA and agents. If two implementations remain during migration, require
   independent parsing and semantic equivalence against the same contract.
   Retain compatibility for existing exports/endpoints or version their replacement.
9. **Bound resource use.** Define metadata/archive size, node count, nesting,
   query time and result limits. Resolve vocabulary dependencies from controlled,
   pinned sources; untrusted models must not trigger arbitrary network/file reads.

## Engineering quantities and agent tools

Reuse existing `open_fdd.ecm_engineering` calculators and reconcile the existing
EQ-VOCAB / EQ-PERSIST / ECM-ADAPT requirements. Preserve quantity kind, numeric
value, unit, design/rated/measured/assumed basis, source evidence, applicable
rating conditions, review state and model revision. Preserve original values and
conversion provenance. Missing optional evidence remains missing; calculations
must name any required inputs that are absent or incompatible.

Keep cooling/heating capacity, electrical input, shaft power, airflow, fluid flow
and efficiency distinct. For example, thermal kW is not electrical kW; a ton of
refrigeration is not a mass unit; percent and fraction need explicit conversion.
Different rating conditions must not be silently averaged. Point readings and
mechanical schedule ratings retain separate identities and meanings.

Require a real model-to-calculator integration fixture with independently checked
expected results and dimensional conversions. An importable Python module does
not prove the adapter works. Calculation results include selected evidence IDs,
assumptions, calculator version and model revision. Agent-facing metadata is
untrusted data, not instructions; all tools retain caller scope and published
read/write permissions.

## Readable product view

Provide a site → equipment → points view with names, units, tags, confirmed
relationships, and visible mapping issues. Keep formatted/copyable/downloadable
Turtle and JSON available. A partial graph must visibly identify incomplete
coverage. Do not suppress warnings to make the model appear complete. Preserve
site navigation, accessibility, and existing mapping edits. Confirm text and
labels render safely when metadata contains HTML-like content.

## Required verification matrix

For each row the implementation plan must name test files, exact commands/CI
jobs, fixtures, expected outcomes, and the evidence artifact. Use actual emitted
output and actual product routes at integration level. Synthetic fixtures need
known answers independent of the implementation being tested.

| ID | Required tests and acceptance |
| --- | --- |
| HR-01 Package compatibility | Old compact-map ZIPs, wrapper layout, utilities/weather, explicit type stamps, append, and CSV/MQTT metadata adapters keep their documented behavior. Compare known FDD/analytics results on unchanged inputs. Rich metadata survives save/restart/export. Invalid new metadata cannot partially overwrite a valid revision. |
| HR-02 Identity | Unit/property tests for Unicode, quotes, backslashes, whitespace, reserved `enc_`, tuple separators, trailing periods, repeated labels, renames and duplicate IDs. Distinct resources stay distinct; conflicting IDs are rejected or explicitly reconciled. Test same building/equipment labels in different tenants. |
| HR-03 Haystack semantics | Parse real Turtle with an independent RDF library, resolve terms against pinned defs, and validate explicit graph constraints/SHACL. Check site/equip/point types, markers, typed literals and references. False/null marker inputs must not silently become present markers. Fail dangling refs and invalid types where the profile forbids them. |
| HR-04 Projection fidelity | Compare graph meaning modulo ordering and blank-node labels. Verify all declared fields, units, provenance, relationships, unmapped inventory and diagnostics. Record intentional omissions. Exercise every supported JSON/RDF import/export direction; a prefix/string presence test is insufficient. |
| HR-05 Mapping quality | Fixtures with two columns assigned to one FDD role, distinct legitimate same-kind sensors, unknown units, unconfirmed parent relations, and intentional exclusions. Keep syntax/domain/FDD-readiness outcomes separate. Require explicit selection evidence before resolving ambiguity. |
| HR-06 Authorization | Two real test tenants with known nonempty own models; confirm identity and both positive controls, then A→B and B→A denial. Cover JSON/TTL downloads, edits/imports, derived caches, queries and any advertised agent/export job paths. Scope admin/viewer/agent behavior to actual permissions; include anonymous/expired credentials. Test forged foreign refs and repeated IDs. A 404 needs an owner-positive existence control; 401 alone is not proof of tenant isolation. |
| HR-07 Revision lifecycle | Atomic failure, reimport/idempotence, update/delete, concurrent revision conflicts, restart, stale export/query cache prevention, and a rollback rehearsal that preserves native metadata and historian data. |
| HR-08 Engineering | Actual typed adapter/calculation with independently derived expected results; unit conversion and basis checks, missing inputs, conflicting evidence and capacity versus power distinctions. Test that unavailable calculators yield a clear unready/error result. |
| HR-09 UI | Vitest coverage for model/validation behavior and browser tests for active-site scope, hierarchy, large point lists, safe text, visible ambiguities, actual downloaded file parsing, and existing mapping edits. |
| HR-10 Graph capability | If central SPARQL is advertised, execute real authenticated point→equipment→site and confirmed supply-path queries with known answers, tenant aggregates, typed filters, errors and bounded cancellation. Verify parser-based query restrictions and controlled external access. Legacy edge query tests do not establish central package graph availability. If unavailable, preserve that status and the outstanding delivery requirement. |
| HR-11 Performance | Seeded representative small/large multi-site models; establish limits before measuring. Compare identical correct outputs for import, persistence, exports and any graph queries. Record counts, cold/warm p50/p95, peak memory, cache/rebuild behavior and bounded concurrency on a suitable host. A skipped large run supplies no large-scale performance claim. |
| HR-12 Evaluator integrity | Deliberately broken model/output/harness fixtures must make qualification fail or block: malformed TTL, empty expected inventory, missing point/unit/ref, foreign data, stale candidate/hash, dropped checks, duplicate check IDs, timeout, absent artifact, unknown status, required BLOCKED/N/A/SKIPPED. Assert nonzero process result and nonqualifying final manifest. |

Run relevant Rust unit/integration tests in CI or a suitable build host; no heavy
local builds on bensbench. Run frontend, Python adapter, qualification-evaluator
and documentation checks where applicable. Extend existing suites instead of
building a disconnected demonstration that cannot exercise the product.

## Stress, deployment and completion

Audit and enhance `scripts/nightly-ot-bench/36_model_ecm_qualification.sh`, its
runner wiring and `scripts/qualification/write_manifest.py` together. Give model
checks stable IDs and an explicit required-set contract. The final manifest must
consume executed semantic results, fixture/candidate identities and artifacts.
HTTP 200, presence of prefixes, or importing an ECM module do not prove readiness.
An unavailable-feature check may pass as capability honesty while the feature's
delivery requirement remains BLOCKED/PARTIAL. Keep those check IDs separate.

Use bounded disposable fixtures in CI/candidate profiles, then the active master's
scheduled enhanced full qualification run. Keep all existing security gates;
adding model tests does not replace auth/ZAP/MQTT or other acceptance. Use smoke
between bounded PRs. Do not rerun a historical S4/V6 window or disturb a live OT
site because a stale plan says to do so. Plan deployment backup, immutable image
pins, candidate verification, rollback and final evidence before promotion.

Update the graph ADR/profile, package authoring/schema docs, JSON/RDF crosswalk,
consumer-route matrix, modeling/ECM examples, GitHub Pages navigation/build,
relevant agent guides/skills, session log, bug tracker and `MILESTONES.md`.
Public fixtures are synthetic and onboarding must work on another developer's
machine without Ben's Downloads, local secrets or live BAS access. Keep private
data and raw sensitive evidence out of public docs.

Completion requires a traceable requirement → implementation → permanent test →
candidate artifact → bug/milestone disposition. Record product and harness SHAs,
profile/schema/fixture hashes, tool versions, counts, run IDs and limitations.
Do not close work by weakening a required set, relabeling failed fixtures, dropping
diagnostics, updating expected answers to match defects, or cancelling unimplemented
scope. Report implementation, verification and release separately.
