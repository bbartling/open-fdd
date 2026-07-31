# Frontend (Phase 1 React home)

**ADR:** [ADR-001 — React SPA and Python exit](../docs/architecture/adr-001-react-rust-modernization.md)

**Historical note:** This directory was marked retired during Milestone A
(“do not recreate React; use `services/ui/` Streamlit”). That lock is
**superseded** for Phase 1+ modernization.

## Rules

- Streamlit (`services/ui/`) remains the **default** product UI until Phase 2 cutover.
- React + TypeScript SPA work lives here (or `web/` / `apps/web/` if relocated)
  and talks **only** to central Rust `/api` — never FastAPI, uvicorn, or
  Streamlit as a backend.
- No `pandas` / `streamlit` runtime dependencies in production frontend packages
  (enforced by `scripts/architecture_react_policy_check.py`).
- Do not start feature slices before M0 ledgers exist under
  `docs/migration/react-rust/`.
- Program kit: `tools/open-fdd-modernization/`.

Until the React project is scaffolded (P1-M2), this folder may contain only docs.
