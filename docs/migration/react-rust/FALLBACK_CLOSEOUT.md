# P2-M5 — Product UI closeout + deletion gates

## Production UI

React is the sole production UI (`frontend/web` → `openfdd-web`). Generation API
defaults to `react`; sticky cookie persists operator preference when used.

**Product UI observation window: CLOSED** (2026-08-01 turnkey).

## Deletion gate checklist

| gate | status |
|---|---|
| Replacement PRs + React paths | PASS (M4–M5 React + P2-M1 closure) |
| Parity / shadow | PASS (`SHADOW_SOAK.md`) |
| Canary PROMOTE | PASS (`CANARY_DECISIONS.md`) |
| Default flip | PASS (P2-M4) |
| Rollback uses immutable old release / compose digests | PASS |
| Call-site scan for leaf twins | PASS — oracle paths remain in `tools/wattlab_export` / PyPI only |

## Disposition

| candidate | action |
|---|---|
| P2-DEL-01…05 | Deleted with React product path |
| P2-DEL-06 weather | Relocate UI copies to oracle/tools; keep `open_fdd` weather |
| P2-DEL-07 | Product UI removal complete |
| P2-DEL-08 | Remove pandas FDD gate from prod images; retain oracle |

Preserve: `open_fdd/ecm_engineering`, `open_fdd/{rules,analytics,reporting}`, `tools/react_parity/**`.
