---
title: ADR — React + Rust modernization
parent: Architecture
nav_order: 2
---

# ADR-001 — React SPA and Python exit (Phase 1)

- **Status:** Accepted (2026-07-31); **Phase 2 cutover completed 2026-08-01**
  (React sole product UI — see `PHASE_2_QUALIFICATION.md`)
- **Program:** [`tools/open-fdd-modernization/`](../../tools/open-fdd-modernization/README.md)
- **Tracking:** [`docs/migration/react-rust/`](../migration/react-rust/README.md)
- **Phase 3:** outlook only ([`PHASE_3_EDGE_STREAMING_OUTLOOK.md`](../../tools/open-fdd-modernization/PHASE_3_EDGE_STREAMING_OUTLOOK.md)); not started.

## Context

The operator UI is a React SPA (`frontend/web` → `openfdd-web`). Production FDD
runs in DataFusion SQL on central. Several checked-in instructions historically
forbade recreating a React UI during Milestone A convergence; that lock is
superseded by this ADR.

## Decision

1. **Product UI:** React + TypeScript SPA (`frontend/web`).
2. **Browser backend:** existing **central** Rust service (`services/central/`).
   No FastAPI (or other Python) compatibility sidecar.
3. **Deterministic analytics / FDD:** DataFusion SQL (`sql_rules/`,
   `crates/fdd_*`). Never move fault math into React or TypeScript.
4. **Delivery:** `openfdd-web` nginx container with same-origin **`/api`** proxy
   to central.
5. **Auth / browser security direction:** JWT (or equivalent) already used by
   central; SPA must carry request IDs; document CSRF/CORS/CSP and safe
   artifact Content-Disposition in the contract milestone (P1-M2). Prefer
   same-origin `/api` to simplify cookies/CORS.
6. **Python during Phase 1:** frozen for product features. Allowed: oracle /
   characterization / fixtures. Disallowed: new production Python services,
   silent pandas FDD fallback, new persistence formats React must later consume.
7. **BACnet / fieldbus / MQTTS:** ownership and write-safety rules are unchanged.
   React never owns UDP 47808 or protocol writes.

## Consequences

- Instruction files that said “do not recreate React” are superseded by this ADR
  for Phase 1+ work.
- New production packages under a React app must not depend on pandas for runtime FDD.
- Policy CI rejects a production React client aimed at a Python service URL.
- Pandas cookbooks and `open_fdd.rules` remain the **oracle** until an explicit
  product decision relocates or archives them (not this ADR).

## Non-goals (this ADR)

- Changing live BACnet write policy.
- Choosing a large UI component library (deferred to P1-M2/M3 evaluation).
- Byte-identical HTML/report formats (semantic parity is the default).

## Related

- [DataFusion-first](datafusion-first.md) — computation boundary (kept, tightened).
- [Job workspaces](job-workspaces.md) — durable Jobs remain central SoT.
- Phase docs: `tools/open-fdd-modernization/PHASE_1_PREP_AND_REACT_PARITY.md`.
