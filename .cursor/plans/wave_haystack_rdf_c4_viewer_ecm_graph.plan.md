---
name: Haystack RDF C4 viewer ECM graph
overview: "Readable site→equip→points UI; scoped ECM adapter math; HR-06 ACL; HR-10 SPARQL honesty or real central queries; HR-08/09."
todos:
  - id: c4-ui
    content: "Mapping/model viewer hierarchy + diagnostics + safe downloads (HR-09)"
    status: pending
  - id: c4-acl
    content: "Two-tenant A↔B positive+negative ACL across JSON/TTL/edit/query/MCP (HR-06)"
    status: pending
  - id: c4-ecm
    content: "Model→open_fdd.ecm_engineering fixture with independent expected math (HR-08)"
    status: pending
  - id: c4-sparql
    content: "Central SPARQL delivery OR keep UNAVAILABLE + outstanding requirement (HR-10)"
    status: pending
  - id: c4-tip-smoke
    content: "VERSION tip → GHCR → smoke"
    status: pending
isProject: false
---

# C4 — Model viewer, ECM consumers, graph capability

**Parent:** [`wave_haystack_rdf_master.plan.md`](wave_haystack_rdf_master.plan.md)  
**Depends on:** C3 exports available to UI/agents  
**HR:** HR-06 Authorization, HR-08 Engineering, HR-09 UI, HR-10 Graph capability  
**Prior:** SEC-ML Soft-OPEN; ECM-ADAPT tip PASS (extend); DM-06/07/08 edge SPARQL ≠ central package graph

## Implementation tasks

### UI (HR-09)

- Site → equipment → points navigation with names, units, tags, confirmed relationships, visible mapping issues.
- Formatted/copyable/downloadable Turtle + JSON; downloaded bytes must parse (browser test).
- Preserve MappingPage edits and active-site scope.
- Safe text rendering for HTML-like metadata (XSS).

### Authorization (HR-06)

- Two real test tenants with **nonempty own models**.
- Owner-positive existence control before foreign 404 claims.
- Cover A→B and B→A on: JSON/TTL downloads, edits/imports, caches, queries, agent/export jobs.
- Admin/viewer/agent scoped to actual permissions; anonymous/expired creds.
- Forged foreign refs + repeated IDs across tenants.

### Engineering (HR-08)

- Reuse `open_fdd.ecm_engineering`; extend W4 adapter.
- Fixture with independently derived expected results (capacity vs power, unit conversion, missing inputs → unready).
- Results carry evidence IDs, assumptions, calculator version, model revision.
- Importable module alone ≠ PASS.

### Graph (HR-10) — bounded choice

**Option A (preferred if schedule allows):** central authenticated SPARQL with real query body, known point→equip→site answers, aggregates, typed filters, errors, bounded cancellation, parser allowlist, no arbitrary network reads.

**Option B:** leave central SPARQL **UNAVAILABLE**; gate-36 honesty check PASS; delivery requirement remains BLOCKED/PARTIAL until a later tip. Legacy `edge/src/model/` tests do **not** close HR-10.

Document chosen option in ADR + consumer-route-matrix before tip merge.

## Permanent tests

| ID | Files | Command | Expected |
| --- | --- | --- | --- |
| HR-09 vitest | `frontend/web/src/**/*.test.ts*` | `npm test` / vitest CI | hierarchy + validation |
| HR-09 browser | Playwright or existing browser suite | discover in `frontend/web` CI | download parse; XSS safe |
| HR-06 ACL | security harness + gate fixtures | `tests/security` + gate 36 rows | A↔B deny with owner-positive |
| HR-08 adapter | `tests/…` or PyPI test path | `pytest …model_adapter…` | known math; unready path |
| HR-10 | if Option A: rust/API integration with SPARQL body; if B: honesty assert | cargo / gate 36 | Option A known answers; Option B UNAVAILABLE ≠ feature PASS |

## Stress / smoke

- Smoke Mapping UI + download on tip.
- Security gates remain enabled; model tests do not replace them.

## Docs

- Pages modeling/onboarding; agent skills package-mapping / ECM
- consumer-route-matrix SPARQL row updated to match Option A/B

## Rollback criteria

- UI tip revert keeps prior MappingPage
- ACL fail-closed on uncertainty
- ECM adapter tip revert leaves PyPI calculators intact (external)

## Exit criteria

- [ ] HR-09 browser + vitest green
- [ ] HR-06 two-tenant matrix green
- [ ] HR-08 math fixture green
- [ ] HR-10 Option A PASS **or** Option B honesty + Soft-OPEN delivery row
- [ ] Tip smoke recorded; C5 unblocked
