---
name: Haystack RDF SPARQL C2–C6 audit train
overview: "Plan-only until Grok stress clears: execute #1123 audit refinements on Haystack C2–C6 (#997/#1000–#1004) — proper Project Haystack defs, real RDF/SPARQL, typed FDD/ECM bindings — then tiny VERSION bump + GHCR refresh; no stale PRs/branches/failed Actions."
todos:
  - id: h0-lock
    content: H0 — plan lock; Grok stress parallel Soft-OPEN; preserve dirty checkout; use worktree for impl; cookbooks sacred
    status: completed
  - id: h1-verify-source
    content: H1 — re-read current master + any open C3 head vs audit SHAs (794c89cb / ed476873); record delta before coding
    status: completed
  - id: h2-c3-repair-vocab
    content: H2 C3/#1001 — pin real Haystack defs libs (ph/phIoT/phScience) + hashes; replace 32-marker allowlist; term resolution from defs
    status: completed
  - id: h3-c3-repair-serialize
    content: H3 C3 — real RDF serializer path; identity/normalize; point id ≠ display name; escape/Unicode/dup ID coverage
    status: completed
  - id: h4-c3-repair-semantics
    content: H4 C3 — standard names/kind/unit/tz/his; validate refs/cardinality; equipRef≠airRef; preserve points despite role ambiguity
    status: completed
  - id: h5-c3-repair-scope-route
    content: H5 C3 — one validated exact scope + ref closure on export; fix inventory-filter vs full-sidecar bug
    status: completed
  - id: h6-c3-repair-tests-docs
    content: "H6 C3 — actual exporter bytes → independent parse/defs/SPARQL KATs; fix profile/crosswalk/fixtures/routes; keep #1001 open until conformance"
    status: completed
  - id: h7-c2-cas-lifecycle
    content: H7 C2/#1000 follow-up — immutable revisions + atomic head/CAS; concurrent/restart/reimport tests; no fake Haystack import ads
    status: completed
  - id: h8-c4-central-graph
    content: H8 C4/#1002 — central scoped RDF from authority+pinned defs; Option B UNAVAILABLE cannot close feature; not edge prototype graph
    status: completed
  - id: h9-c4-sparql-bindings
    content: H9 C4 — server SPARQL templates → typed binding contract (scope/revs/IDs/roles/units/evidence); inheritance from pinned ontology
    status: completed
  - id: h10-c4-consumers
    content: H10 C4 — one DataFusion FDD path + one Python ECM path on exact bindings; cache invalidation; query budgets/authz
    status: completed
  - id: h11-c4-history-ecm
    content: H11 C4/#1017 bind — approved provider/series only; standard eng defs; ECM expected math; no arbitrary URL fetch
    status: completed
  - id: h12-integration-acceptance
    content: H12 — ZIP→RDF/SPARQL→bindings→Parquet/DataFusion integration KATs; dual-tenant ACL; decoy ID/label negatives
    status: completed
  - id: h13-c5-gate36
    content: H13 C5/#1003 — gate-36 required-set + negatives (wrong NS, stale defs, missing artifact, blocked/skipped); no soft greenwash
    status: completed
  - id: h14-c5-perf
    content: H14 C5 — define budgets then measure p50/p95/RSS/cancel on suitable host; skipped large = PARTIAL claim
    status: completed
  - id: h15-c6-candidate
    content: "H15 C6/#1004 — candidate tip smoke + rollback + enhanced qual identities; close #997 only with evidence"
    status: completed
  - id: h16-docs-skills
    content: H16 — update rollout ADR profile crosswalk routes ECM skills AGENTS SESSION_LOG MILESTONES (history preserved)
    status: completed
  - id: h17-hygiene-ci
    content: H17 — push all tip results to GitHub PRs; fix Actions until green; merge; delete branches; no stale open PRs (still stop before H18)
    status: completed
  - id: h18-version-ghcr
    content: "H18 FINAL — HARD STOP: ask operator before VERSION bump / GHCR publish / pin; do not start H18 until explicit go"
    status: completed
isProject: true
---

# Haystack RDF / SPARQL C2–C6 audit train (2026-10-04)

**Status:** **DONE via master finish** (tip `sha-215e159` / 3.5.65). H0–H18 Cursor impl/hygiene/VERSION/GHCR complete. **Left = live Soft-OPEN only:** C6 smoke + close/evidence on #997/#1003/#1004/#1123 (Grok window) — not unchecked H8–H18 code tips.

**GitHub:** [#1123](https://github.com/bbartling/open-fdd/issues/1123) (audit refinements) · [#997](https://github.com/bbartling/open-fdd/issues/997) master · [#1000](https://github.com/bbartling/open-fdd/issues/1000)–[#1004](https://github.com/bbartling/open-fdd/issues/1004) C2–C6

**Audit SoT:**
- [`.cursor/plans/haystack_rdf_sparql_astra_audit_20261003.plan.md`](haystack_rdf_sparql_astra_audit_20261003.plan.md)
- [`.cursor/plans/haystack_rdf_sparql_audit_issue_20261003.md`](haystack_rdf_sparql_audit_issue_20261003.md)
- Existing wave plans: [`wave_haystack_rdf_master.plan.md`](wave_haystack_rdf_master.plan.md) + C1–C6 children · [`pr_haystack_rdf_track_wrapper.plan.md`](pr_haystack_rdf_track_wrapper.plan.md)
- Spec: [`openfdd_agent_spec/HAYSTACK_RDF_ROLLOUT.md`](../../openfdd_agent_spec/HAYSTACK_RDF_ROLLOUT.md) · [`docs/architecture/ADR_data_model_graph.md`](../../docs/architecture/ADR_data_model_graph.md)

**Audited immutable heads (re-verify before coding):** master `794c89cb…` · C3 PR #1122 head `ed476873…` (later merges may already differ — record delta in H1).

## Goal

Project Haystack is the **primary semantic vocabulary**. Real SPARQL drives semantic selection/applicability through **typed bindings** into Parquet/DataFusion and external ECM. Preserve JSON/ZIP authoring and DataFusion math. Open-FDD defines only narrow application bindings / true vocabulary gaps — **not** a parallel HVAC ontology.

## Architecture locks

- **Same data-model process:** `openfdd_package_v1` ZIP + JSON column/role maps + CSV (and package append) remain the authoring/import path into central. Haystack RDF is **derived** from committed native metadata — not a replacement upload format.
- **MQTTS streams OK:** fieldbus→MQTTS→historian stays a first-class ingest path into the same Parquet/DataFusion store. This train must not break MQTTS continuity or invent a second telemetry pipeline. History connectors (#1017) bind approved provider/series ids only.
- Authority: committed package/native metadata per tenant/site revision → derived central RDF dataset + pinned Haystack defs.
- SPARQL answers graph questions; DataFusion computes time-series / fault confirmation.
- SQL cookbooks + pandas oracle stay sacred ([`patch_all_open_issues_master.plan.md`](patch_all_open_issues_master.plan.md) docs-guard).
- Edge `edge/src/model` prototype ≠ package graph. C4 Option B honest `UNAVAILABLE` cannot close graph-driven features.
- #1111 DataFrame inventory ≠ shipped parity — verify before trusting #1078 closed state.
- Prior mega train tip `sha-4251505` Soft-OPEN for Grok live stress — this train does not claim FQ.

## Global constraints

- Continue existing #997 / C2–C6 PR train; no competing branch war.
- Preserve active dirty checkout / plans / evidence; implement in isolated worktree.
- One cargo at a time; **`cargo clean` after local compiles** (bensbench disk).
- No local heavy stack `docker build`; no `docker compose down -v`; never delete `workspace/`.
- No secrets in logs/PRs; SECURITY.md for sensitive findings.
- Each PR: exact behavior + commands/results + remaining gaps; green compile ≠ semantic conformance.
- **Train exit hygiene:** no open failed Actions on tip heads; merge → delete remote+local branches; then **H18** VERSION + GHCR newest-by-created.

## Wall-clock sequence

```text
H0–H1   lock + source verify
H2–H6   C3 repair train (#1001 / reopen conformance if needed)
H7      C2 CAS lifecycle follow-up (#1000)
H8–H11  C4 central graph + bindings + consumers (#1002; #1017 bind)
H12     integration acceptance KATs
H13–H14 C5 gate-36 + perf (#1003)
H15     C6 candidate + close #997 with evidence (#1004)
H16     docs/skills/milestones
H17     CI/branch hygiene continuous
H18     tiny VERSION bump → GHCR refresh → pin → stop (Grok live)
```

## H2–H6 — First bounded change: C3 repair (#1001 / #1122 train)

1. **Vocab pin:** Official versioned multi-library Haystack RDF artifacts + dependency hashes. Resolve `ph` / `phIoT` / `phScience` with exact case-sensitive symbols. Docs page version ≠ artifact pin. Include documented mapping helpers (e.g. `ph:hasTag`) without inventing tag defs.
2. **Serializer:** Replace hand-built unsafe Turtle with real RDF-term/serializer. Cover trailing `.`, Unicode, quotes, `/`, `enc_`, tuples, whitespace, duplicate IDs. Normalize or reject noncanonical identities. Point identity ≠ mutable CSV header/display name. Document persistent IRI vs blank-node interchange; no scope collisions.
3. **Semantics:** Model names, kind, point unit, timezone, historization with standard defs. Distinguish `unit` string metadata vs numeric tags with units. Preserve or explicitly reject/report every supported native field. At audit head `ref_equip`, `site_ref`, provenance, engineering quantities ignored; unknown JSON silently dropped — **not** lossless roundtrip.
4. **Refs:** Validate site/equip/point refs, existence, cardinality, conflicts. Point `siteRef`/`equipRef` agree with scope. Sensor/cmd/sp per profile. `equipRef` ≠ generic parent-AHU supply; use `airRef` only with evidence.
5. **Role ambiguity:** Keep valid semantic points when SQL role candidates are ambiguous. FDD selection/evidence separate; operator exclusions explicit. Update C3 plan/crosswalk that removes semantic existence for role ambiguity.
6. **Scope bug:** `equipment_id` must not filter inventory diagnostics while exporting all sidecar metadata. One validated exact scope + defined reference closure. Inventory failure must not drop diagnostics and emit a complete-looking projection.
7. **Tests/docs:** Actual Rust exporter/API bytes as artifacts → independent parse, every standard IRI vs pinned defs, graph constraints, known-answer SPARQL. Python RDFLib hand-written Turtle = syntax smoke only. Missing deps/artifacts fail qualification. Update `haystack-rdf-profile.md`, crosswalk, fixtures, route claims. Keep #1001 open until conformance acceptance is real.

## H7 — C2 foundation follow-up (#1000)

Typed metadata + revision lifecycle before graph consumers depend on it. Immutable revision objects; atomic head publication or equivalent; per-tenant/site serialized CAS; unique/content-addressed revisions; idempotence; validate before publish; recovery/hash consistency. Tests: concurrent edits, injected publication failures, hard restart, reimport, update/delete, cache invalidation, rollback, unchanged historian. Old compact ZIPs / weather / append compatible; rich metadata rejection explicit. Preserve supported JSON fields across import→save→restart→export. Do not advertise Haystack JSON/RDF import until implemented+tested.

## H8–H11 — C4 delivery (#1002)

Amend C4 plan: Option B interim UNAVAILABLE cannot close the feature. One **central** scoped RDF dataset from committed authority + pinned defs.

- Server-owned parsed SPARQL templates + typed parameters → binding contract: scope, model/defs/binding revision, stable equipment/point IDs, canonical role IDs, approved provider/series IDs, units/kinds/quality, evidence; cardinality + selection approval; ontology inheritance (not opaque IDs/labels).
- Consumers: one FDD applicability/input path through DataFusion/Parquet; one external Python ECM path. Cache keys include model/defs/binding/query versions + scope; invalidate on edit/delete/rollback.
- Query controls: authn, named graphs + authz, AST allowlist, no uncontrolled federation, bounded resources, cancellation; `LIMIT` ≠ execution budget.
- #1017 history: bind to approved scoped provider/series + nonsecret connection refs; preserve source IDs/tz/units/quality/conversion/model revision; raw observations stay out of RDF graph.
- Engineering defs only in declared meaning/domain; search pinned vocab first; minimal documented extensions for gaps; reuse `open_fdd.ecm_engineering` with independent expected results.

## H12 — Integration acceptance (must demonstrate)

- ZIP import → committed model → central RDF/SPARQL → typed bindings → Parquet/DataFusion with known expected data + real product routes.
- Hold telemetry fixed; change only semantic binding/topology → predicted applicability/result change; remove/corrupt binding → unready (no silent sidecar bypass).
- Duplicate sensors visible; unresolved selection unready; approved choice resolves intended; unknown units / contradictory refs cannot pass via first-column.
- Opaque ID/label renames unchanged; decoy AHU/VAV/weather strings ≠ membership; legitimate AHU subclasses.
- Two nonempty synthetic tenants + foreign-negative on all advertised export/query/cache/job/agent/history surfaces.
- Independent parser/defs/constraint/SPARQL; isomorphism / typed JSON roundtrip only for advertised directions; index differential equivalence.
- Real ECM math with dimensional conversions + unready diagnostics.
- DataFusion plan evidence: bounded time/equipment/column reads; no fetch-all-before-graph-selection.

## H13–H15 — C5 / C6

- Gate 36: fix required check IDs/set semantics; negatives for wrong NS, malformed RDF, empty expected sets, absent point/unit/ref, stale revision/defs hash, missing artifact, dropped/dup check IDs, timeout, required blocked/skipped → nonzero + nonqualifying manifest.
- Perf: define sizes/budgets first; measure cold/warm p50/p95, peak RSS, export/rebuild/invalidation, concurrent tenants, expensive joins, cancellation.
- C6: immutable source/image/harness/schema/defs/fixture identities; actual route artifacts; rollback; bounded synthetic smoke between PRs; enhanced window via authorized deployment rules. Close #997 only with evidence.

## H16 — Docs / skills

Rollout spec, graph ADR, architecture/data contract, profile, package docs, JSON/RDF crosswalk, route matrix, ECM adapter docs, capability ledger, canonical skills, AGENTS rules, SESSION_LOG, BUG_REPORT, MILESTONES — annotate resolved/reopened; do not erase history.

## H17–H18 — Hygiene + GHCR exit

| Step | Rule |
| --- | --- |
| Per tip | Local verify → **push branch** → **`gh pr create`/update** → Actions green → `gh pr merge` → delete remote **and** local branch / worktree |
| **H17** | All train results must be on GitHub PRs (not local-only); fix Actions until green; merge clean tips |
| Actions | Fix red CI; cancel superseded duplicate runs; leave tip heads green |
| Disk | `cargo clean` after local Rust batches |
| **H18 FINAL** | **HARD STOP — ask the human first.** Only after explicit operator go: tiny workspace **patch** `VERSION` bump → master green → GHCR publish → `./scripts/ghcr_newest_by_created.py` pin → document tip → **stop** |
| Live | Grok owns stress / security pen-test; no FQ / `fully_qualified=true` from this train alone |

## Success definition

- [#1123](https://github.com/bbartling/open-fdd/issues/1123) acceptance refinements satisfied or Soft-OPEN with explicit evidence gaps.
- C3 conformance real (not greenwash); C2 CAS sound; C4 graph-driven bindings used by at least one FDD + one ECM path; C5/C6 honest.
- Sacred cookbooks untouched.
- No stale open PRs / gone local tip branches / failed Actions on the release tip.
- Newest GHCR tip pinned after VERSION bump; handoff note for Grok if live re-stress needed.

## Out of scope

- Competing Open-FDD ontology / vibe-rewriting SQL↔pandas cookbooks.
- Live OT ActiveScan, Nessus license assessment, BACnet writes (Grok/Kali/human windows).
- Claiming full Haystack interoperability from a prefix, static fixture, or compile-only green.
