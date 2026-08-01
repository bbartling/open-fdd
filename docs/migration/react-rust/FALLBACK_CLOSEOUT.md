# P2-M5 — Fallback observation closeout + deletion gates

## Fallback window

React is the production default (`P2-M4` / `#641`). Streamlit remains recoverable via:

- sticky cookie / `PUT /api/ui/generation` → `streamlit`
- `docker/compose.central.yml` with `OPENFDD_UI_GENERATION_DEFAULT=streamlit`

**Fallback observation window: CLOSED** for product default purposes (2026-08-01 turnkey).
Further Streamlit usage is emergency rollback only until Prompt 7 removal.

## Deletion gate checklist (Prompt 6)

| gate | status |
|---|---|
| Replacement PRs + React paths | PASS (M4–M5 React + P2-M1 closure) |
| Parity / shadow | PASS (`SHADOW_SOAK.md`) |
| Canary PROMOTE | PASS (`CANARY_DECISIONS.md`) |
| Default flip | PASS (P2-M4) |
| Rollback uses immutable old release / compose, not twin code | PASS (`ROLLBACK_DRILL.md`) |
| Call-site scan for leaf twins | PASS — leaves are still imported by `streamlit_app` / `agent_api`; **cannot delete leaves while Streamlit entry remains** |

## Disposition

**Leaf twins (P2-DEL-01…06) delete with Prompt 7** (Streamlit product removal), not as standalone PRs that hollow out a still-shipping Streamlit fallback.

| candidate | action in Prompt 7 |
|---|---|
| P2-DEL-01…05 | Delete with Streamlit entry + CI rewrite |
| P2-DEL-06 weather | Relocate UI copies to oracle/tools; keep `open_fdd` weather |
| P2-DEL-07 | Streamlit product removal vehicle |
| P2-DEL-08 | Remove pandas FDD gate from prod images; retain oracle |

Preserve: `open_fdd/ecm_engineering`, `open_fdd/{rules,analytics,reporting}`, `tools/react_parity/**`.

## Next

P2-M6 / Prompt 7 — Streamlit product removal PR (compose + CI + entry/twins).
