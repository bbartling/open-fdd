---
description: Phase 1 React/Rust parity — require openfdd_agent_spec + React SPA skill
globs:
  - frontend/web/**
  - docs/migration/react-rust/**
  - tools/open-fdd-modernization/**
  - openfdd_agent_spec/**
  - tests/react_parity/**
alwaysApply: false
---

# Open-FDD Phase 1 React parity

When editing files matched by this rule you are in the React/Rust product program.

## Required reads before substantive edits

1. `AGENTS.md` (repo root)
2. `openfdd_agent_spec/AGENTS.md`
3. `tools/open-fdd-modernization/AGENT_SKILL_BRIDGE.md`
4. `openfdd_agent_spec/skills/openfdd-react-spa/SKILL.md`
5. `tools/open-fdd-modernization/AGENTS.md`
6. `tools/open-fdd-modernization/AGENT_EXECUTION_SYSTEM.md`
7. Current ledgers under `docs/migration/react-rust/`

Also load the matching `openfdd_agent_spec/skills/*` skill when touching SQL FDD,
cookbooks, GHCR, ECM, or ownership.

## Architecture law

- React presentation only (`frontend/web`).
- APIs/jobs/persistence = `services/central` (Rust).
- Deterministic FDD/analytics = DataFusion / `sql_rules/`.
- Python = oracle/characterization only in Phase 1.
- **No FastAPI** and no Python browser sidecar.
- No BACnet writes from React.
- One bounded `P1-M?-??` PR; update ledgers + `openfdd_agent_spec/BUILD_CHECKPOINTS.md` when status changes.

## Parity method

Follow the openfdd-react-spa skill workflow: inventory → measure → contract →
implement → verify. Use product screenshots and ledgers as the visual reference.
Document intentional differences in `docs/migration/react-rust/DECISIONS.md`.
