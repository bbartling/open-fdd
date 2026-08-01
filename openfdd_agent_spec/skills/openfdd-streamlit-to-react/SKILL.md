---
name: openfdd-streamlit-to-react
description: >-
  Open-FDD Streamlit→React maintenance and residual parity. Use when editing
  frontend/web, diagnosing React vs archived Streamlit mismatches, or residual
  CAP-* work. Pair with tools/open-fdd-modernization/skills/streamlit-to-react
  and Rust/central contracts. Phase 1+2 complete; Phase 3 edge/live is outlook-only.
---

# Open-FDD Streamlit → React

## Goal

Maintain React UX in `frontend/web` with authority on **central Rust +
DataFusion**. Python is oracle-only. No FastAPI sidecar. Streamlit is archived
(not the product comparison default for new features).

## Program status

| Phase | Status |
| --- | --- |
| Modernization Phase 1 | Exit approved (`PHASE_1_QUALIFICATION.md`) |
| Modernization Phase 2 | Exit approved (`PHASE_2_QUALIFICATION.md`) |
| Modernization Phase 3 | Outlook only (`PHASE_3_READINESS.md`) — no live BACnet/MQTT redesign without auth |
| Skill compliance | See `docs/migration/react-rust/PHASE_3_READINESS.md` |

**Do not confuse** Milestone A “Phase 2/3” (shared contracts / vibe19) with
modernization Phase 2/3.

## Read first (required)

1. [`../../AGENTS.md`](../../AGENTS.md) (openfdd_agent_spec)
2. [`../../../tools/open-fdd-modernization/AGENT_SKILL_BRIDGE.md`](../../../tools/open-fdd-modernization/AGENT_SKILL_BRIDGE.md)
3. **Canonical skill:**
   [`../../../tools/open-fdd-modernization/skills/streamlit-to-react/SKILL.md`](../../../tools/open-fdd-modernization/skills/streamlit-to-react/SKILL.md)
4. Open-FDD overlay:
   [`../../../tools/open-fdd-modernization/AGENTS.md`](../../../tools/open-fdd-modernization/AGENTS.md)

Then selectively:

- [component-mapping.md](../../../tools/open-fdd-modernization/skills/streamlit-to-react/references/component-mapping.md)
- [parity-verification.md](../../../tools/open-fdd-modernization/skills/streamlit-to-react/references/parity-verification.md)
- [sidecar-architecture.md](../../../tools/open-fdd-modernization/skills/streamlit-to-react/references/sidecar-architecture.md)
  — **map FastAPI → central Rust** for this repo

## Open-FDD hard rules

- Browser → React → `/api` on central only.
- Do not move FDD/analytics math into TypeScript.
- Do not add a Python API service for the React app.
- Update `docs/migration/react-rust/` ledgers in the same PR.
- One bounded milestone ID per PR; follow
  [`../openfdd-milestone-a-pr/SKILL.md`](../openfdd-milestone-a-pr/SKILL.md) spirit
  (inventory → characterize → contract → implement → parity → docs).
- Update [`../../BUILD_CHECKPOINTS.md`](../../BUILD_CHECKPOINTS.md) when
  modernization status changes.

## Workflow

Follow the numbered workflow in the canonical streamlit-to-react `SKILL.md`
exactly, with Open-FDD paths:

| Generic skill concept | Open-FDD path |
| --- | --- |
| Streamlit app (archive) | `services/ui/streamlit_app.py`, `services/ui/app/` |
| React app | `frontend/web/` |
| API | `services/central/` `/api/*` |
| Oracle | `open_fdd.*`, `tools/react_parity/`, cookbooks |
| Evidence | `docs/migration/react-rust/` |

## Done when

Parity classes for the slice are recorded (not UNKNOWN when claiming DONE),
tests/CI green, and ledgers + BUILD_CHECKPOINTS reflect the merge.
