---
name: Haystack RDF C2 metadata persistence
overview: "Smallest versioned JSON metadata extension for points/tags/units/refs/provenance/EQ; preserve ZIP/JSON/append; tenant atomic revisions; HR-01/02/07."
todos:
  - id: c2-schema
    content: "Design versioned native metadata sidecar/schema; trace package.rs importer"
    status: pending
  - id: c2-import
    content: "Import path accepts old ZIPs + optional rich metadata; no fabricate on old pkgs"
    status: pending
  - id: c2-persist
    content: "Tenant-scoped atomic revision store; conflict/delete/invalidation"
    status: pending
  - id: c2-eq-persist
    content: "EQ-PERSIST capacities/basis through save/restart/export"
    status: pending
  - id: c2-tests
    content: "Permanent Rust tests HR-01/02/07 + CI cargo jobs"
    status: pending
  - id: c2-tip-smoke
    content: "VERSION tip → GHCR → backup/re-pin → smoke (not FQ)"
    status: pending
isProject: false
---

# C2 — Compatible metadata persistence

**Parent:** [`wave_haystack_rdf_master.plan.md`](wave_haystack_rdf_master.plan.md)  
**Depends on:** C1 profile/crosswalk locked  
**HR:** HR-01 Package compatibility, HR-02 Identity, HR-07 Revision lifecycle (+ EQ-PERSIST)  
**Prior:** DM-04/05 Soft-OPEN; EQ-PERSIST Soft-OPEN

## Implementation tasks

1. Trace `edge/src/csv_ingest/package.rs` (+ central package handlers in `services/central/src/routes.rs`) before choosing sidecar name.
2. Add **smallest** versioned extension (e.g. `openfdd_semantic_meta_v1`) for:
   - point tags, units, refs, provenance, engineering quantities (kind/value/unit/basis/evidence/review)
   - equipment/site labels and confirmed relationships only
3. Preserve:
   - compact-map ZIPs, wrapper layout, utilities/weather, stamped `equipType`, append API
   - mapped SQL role behavior for FDD/analytics
4. Persistence rules:
   - one authority per tenant/site revision
   - atomic import failure (no partial overwrite of valid revision) — HR-01/07
   - concurrent-edit conflict handling
   - deletion + cache invalidation hooks for exporters (C3)
5. Identity: extend DM-01/02 tests for Unicode, quotes, backslashes, whitespace, reserved `enc_`, tuple separators, trailing periods, renames, duplicate IDs, cross-tenant same labels — HR-02.

## Permanent tests

| ID | Files (create/extend) | Command | Expected |
| --- | --- | --- | --- |
| HR-01 old ZIP | `edge` package tests + fixture ZIPs | `cargo test -p … package` (discover crate from Cargo.toml) | old packages bit-identical semantics |
| HR-01 rich roundtrip | save→restart→export fixture | integration test | metadata retained |
| HR-01 invalid meta | bad sidecar | cargo test | prior revision intact |
| HR-01 append | append package API fixture | cargo / API integration | append OK |
| HR-02 identity matrix | rust unit + vitest if TS shared | cargo + `npm test` dataModel | distinct resources; reject conflicts |
| HR-07 atomic/conflict | revision tests | cargo test | conflict explicit; rollback rehearsal dry-run |
| EQ-PERSIST | capacity fixture | cargo/pytest | values survive reload |

**CI:** existing Rust workflow jobs that already run `open_fdd_edge` / central tests — extend; do not invent disconnected crates. Frontend vitest if encoding shared with TS.

## Stress / smoke

- After GHCR tip: Railway/local smoke only (`./scripts/openfdd_stack_up.sh` path per CONTAINER_AGENT) — import old synth package + new rich fixture.
- Gate 36 may still be Soft-OPEN until C5.

## Docs

- `docs/agent/PACKAGE_AUTHORING.md`, `docs/modeling/package-schema.md`
- Crosswalk: which fields persist natively vs export-only

## Rollback criteria

- Tip revert / prior `sha-*` pin restores prior importer.
- Historian Parquet untouched by metadata rollback.
- Old ZIPs must import on tip **and** on rollback pin (compatibility test before merge).

## Exit criteria

- [ ] Schema merged; old ZIP golden FDD/analytics unchanged on fixtures
- [ ] Atomic revision + conflict tests green in CI
- [ ] EQ-PERSIST Soft-OPEN → tip evidence or honest residual
- [ ] VERSION tip published; smoke evidence path recorded
- [ ] C3 unblocked
