---
title: ADR — React + Rust modernization
parent: Architecture
nav_order: 2
---

# ADR-001 — React SPA and Python exit (Phase 1)

- **Status:** Accepted (2026-07-31); **Phase 2 cutover completed 2026-08-01**
  (React sole product UI; Streamlit archived — see `PHASE_2_QUALIFICATION.md`)
- **Program:** [`tools/open-fdd-modernization/`](../../tools/open-fdd-modernization/README.md)
- **Tracking:** [`docs/migration/react-rust/`](../migration/react-rust/README.md)
- **Phase 3:** outlook only ([`PHASE_3_EDGE_STREAMING_OUTLOOK.md`](../../tools/open-fdd-modernization/PHASE_3_EDGE_STREAMING_OUTLOOK.md)); not started.

## Context

The operator UI today is Streamlit (`services/ui` → `openfdd-ui`). Production FDD
already runs in DataFusion SQL on central. Several checked-in instructions
historically forbade recreating a React UI. That lock was a **current-state**
guard during Milestone A convergence, not a permanent product prohibition.

We need a contract-first strangler migration to a React SPA that talks only to
Rust-owned APIs, with Streamlit retained as fallback until Phase 2 cutover.

## Decision

1. **Product UI (target):** React + TypeScript SPA.
2. **Browser backend:** existing **central** Rust service (`services/central/`).
   No FastAPI (or other Python) compatibility sidecar.
3. **Deterministic analytics / FDD:** DataFusion SQL (`sql_rules/`,
   `crates/fdd_*`). Never move fault math into React or TypeScript.
4. **Delivery:** static assets served by central **or** a separately deployable
   web container, with one stable **`/api` origin** contract for the browser.
5. **Auth / browser security direction:** JWT (or equivalent) already used by
   central; SPA must carry request IDs; document CSRF/CORS/CSP and safe
   artifact Content-Disposition in the contract milestone (P1-M2). Prefer
   same-origin `/api` to simplify cookies/CORS.
6. **Streamlit:** was the default product UI and behavioral reference during
   Phase 1. React shipped behind a reversible feature flag. **After Phase 2
   exit (2026-08-01):** React is the sole production UI; Streamlit is archived
   (`services/ui/ARCHIVED.md`, compose profile `streamlit-legacy`). Deletion of
   remaining archive sources is optional follow-on, not required for Phase 2 exit.
7. **Python during Phase 1:** frozen for product features. Allowed: oracle /
   characterization / fixtures. Disallowed: new production Python services,
   silent pandas FDD fallback, new persistence formats React must later consume.
8. **BACnet / fieldbus / MQTTS:** ownership and write-safety rules are unchanged.
   React never owns UDP 47808 or protocol writes.

## Consequences

- Instruction files that said “do not recreate React” are superseded by this ADR
  for Phase 1+ work; historical wording may remain as struck context.
- New production packages under a React app must not depend on Streamlit or
  pandas for runtime FDD.
- Policy CI rejects a production React client aimed at a Python service URL.
- Pandas cookbooks and `open_fdd.rules` remain the **oracle** until an explicit
  product decision relocates or archives them (not this ADR).

## Non-goals (this ADR)

- Deleting Streamlit or production Python images.
- Changing live BACnet write policy.
- Choosing a large UI component library (deferred to P1-M2/M3 evaluation).
- Byte-identical HTML/report formats (semantic parity is the default).

## Related

- [DataFusion-first](datafusion-first.md) — computation boundary (kept, tightened).
- [Job workspaces](job-workspaces.md) — durable Jobs remain central SoT.
- Phase docs: `tools/open-fdd-modernization/PHASE_1_PREP_AND_REACT_PARITY.md`.
