---
name: openfdd-streamlit-to-react
description: >-
  Open-FDD React product UI work. Use when editing frontend/web, Overview
  analytics wiring to central DataFusion, or CAP-* ledger updates. Pair with
  tools/open-fdd-vibe21-production and capabilities.yaml. Product UI is React
  only — do not treat Streamlit as a shipping surface.
---

# Open-FDD React product UI

## Goal

Maintain React UX in `frontend/web` with authority on **central Rust +
DataFusion**. Python is oracle-only (PyPI / vibe19). No FastAPI sidecar.
**No Streamlit product UI** — in-repo Streamlit/`openfdd-ui`/overview-oracle are
cutover-delete targets, not feature baselines for new work.

## Program status

| Program | Status |
| --- | --- |
| Turnkey Rust cutover | Active — React + DataFusion product; delete Streamlit tree after WattLab relocate |
| Modernization Phase 1+2 | Architecture direction / exit docs — **not** Vibe 21 P1-G0 |
| Vibe 21 recovery | Active — [`tools/open-fdd-vibe21-production/`](../../../tools/open-fdd-vibe21-production/README.md) |
| Capability ledger | [`capabilities.yaml`](../../../docs/migration/react-rust/capabilities.yaml) |
| Modernization Phase 3 | Outlook only — no live BACnet/MQTT redesign without auth |

**Do not confuse** Milestone A “Phase 2/3” (shared contracts / vibe19) with
modernization Phase 2/3 or Vibe 21 Phase 1 recovery.

## Read first (required)

1. [`../../AGENTS.md`](../../AGENTS.md) (openfdd_agent_spec)
2. [`../../../tools/open-fdd-vibe21-production/prompts/MASTER_PRODUCTION_LOOP.md`](../../../tools/open-fdd-vibe21-production/prompts/MASTER_PRODUCTION_LOOP.md)
3. [`../../../docs/migration/react-rust/capabilities.yaml`](../../../docs/migration/react-rust/capabilities.yaml)
4. Historical migration skill (context only — product is React-only now):
   [`../../../tools/open-fdd-modernization/skills/streamlit-to-react/SKILL.md`](../../../tools/open-fdd-modernization/skills/streamlit-to-react/SKILL.md)
5. Bridge:
   [`../../../tools/open-fdd-modernization/AGENT_SKILL_BRIDGE.md`](../../../tools/open-fdd-modernization/AGENT_SKILL_BRIDGE.md)

## Open-FDD hard rules

- Browser → React → `/api` on central only.
- Overview charts: `POST /api/analytics/*` envelopes → client Plotly
  (`frontend/web/src/api/centralOverview.ts`). No Python overview-oracle in product path.
- Do not move FDD/analytics math into TypeScript.
- Do not add a Python API service for the React app.
- Do not resurrect Streamlit/`openfdd-ui` as product UI.
- **Internet-facing:** never render bench credential paths, default passwords,
  JWT/auth dumps, or `auth_required` diagnostics on login/product surfaces.
  Ops handoff stays in docs/scripts only.
- Update `capabilities.yaml` statuses honestly in the same PR; never mark
  `QUALIFIED` without evidence paths.
- Forbid “Phase complete” claims without a qualification manifest / ledger proof.
- One bounded milestone ID per PR (Master Loop / PR matrix).
- Update [`../../BUILD_CHECKPOINTS.md`](../../BUILD_CHECKPOINTS.md) + append
  [`../../SESSION_LOG.md`](../../SESSION_LOG.md) when product truth changes.
- Keep `openfdd_agent_spec/` in sync whenever cutover / UI / analytics ownership changes.
- Unity WebGL arrives later as an **external ZIP** (Phase 4) — do not embed Unity Editor.

## Workflow

Follow the Master Loop selected PR. Validate:

```bash
python3 scripts/validate_capabilities_ledger.py
```

## Stop / escalate

- Missing Vibe 21 oracle path for Phase 2+ work.
- BAS write or publish authority not granted.
- Request to skip P1-G0 / claim QUALIFIED without evidence.
- Request to ship product features via Streamlit or overview-oracle.
