---
title: React / Rust modernization
parent: Migration
nav_order: 20
---

# React / Rust modernization (Phase 1+)

**ADR:** [ADR-001 — React SPA and Python exit](../architecture/adr-001-react-rust-modernization.md)

**Program kit (authoritative milestones / PR matrix / agent loop):**
[`tools/open-fdd-modernization/`](../../tools/open-fdd-modernization/README.md)

## Status

| Item | State |
|------|-------|
| Architecture decision | Accepted (ADR-001) |
| Streamlit product UI | Default / fallback (`compose.central.yml`) |
| React SPA | Phase 1 exit approved — behind `OPENFDD_REACT_UI`; `compose.react.yml` |
| Production Python exit | Phase 2 (not started; see CUTOVER_LOG) |

## Durable ledgers (this directory)

| File | Role |
|------|------|
| [DECISIONS.md](DECISIONS.md) | Product/architecture calls |
| [CAPABILITY_MATRIX.md](CAPABILITY_MATRIX.md) | User scenarios → owners |
| [PYTHON_EXIT_MATRIX.md](PYTHON_EXIT_MATRIX.md) | Every production Python entry |
| [API_CONTRACT_MATRIX.md](API_CONTRACT_MATRIX.md) | Versioned contracts |
| [PARITY_EVIDENCE.md](PARITY_EVIDENCE.md) | Fixture hashes / parity results |
| [SESSION_LOG.md](SESSION_LOG.md) | Agent session append-only log |
| [PHASE_1_QUALIFICATION.md](PHASE_1_QUALIFICATION.md) | Phase 1 exit evidence pack |
| [NO_PYTHON_STACK.md](NO_PYTHON_STACK.md) | React compose topology |
| [PHASE_2_DELETION_CANDIDATES.md](PHASE_2_DELETION_CANDIDATES.md) | Enumerated deletes (not executed) |
| [CUTOVER_LOG.md](CUTOVER_LOG.md) | Phase 2 cutover records |

Ledgers are seeded in **P1-M0-02**. Update them in the same PR as implementation.

## Architecture law

```text
Browser → React SPA → central Rust /api → DataFusion SQL + jobs/artifacts
Python → oracle / characterization only during Phase 1 (no FastAPI sidecar)
```

## Agent bootstrap

1. Read ADR-001 and this README.
2. Read `tools/open-fdd-modernization/AGENT_EXECUTION_SYSTEM.md`.
3. Pick **one** PR ID from `MILESTONE_PR_MATRIX.md`.
4. Do not start React feature PRs before M0 gate (ADR + ledgers).
