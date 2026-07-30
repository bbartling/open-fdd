# Migration matrix (pointers + status)

Do not fork parallel truth. Update existing audits when code changes.

| Document | Role |
| --- | --- |
| [`docs/migration/VIBE19_VIBE20_OPENFDD_AUDIT.md`](../../docs/migration/VIBE19_VIBE20_OPENFDD_AUDIT.md) | Cross-product audit |
| [`docs/migration/vibe19_parity_matrix.md`](../../docs/migration/vibe19_parity_matrix.md) | vibe19 capability parity |
| [`docs/migration/vibe20_integration_matrix.md`](../../docs/migration/vibe20_integration_matrix.md) | WattLab / vibe20 integration |
| [`docs/rules/cookbook/parity-matrix.md`](../../docs/rules/cookbook/parity-matrix.md) | SQL ↔ pandas rule honesty |
| [`docs/migration/OFDD_065_076_PARITY.md`](../../docs/migration/OFDD_065_076_PARITY.md) | Liberty B50/B100 FAULT deltas + Gate A–C |
| [`docs/mcp-agents/companion-wattlab-energyplus.md`](../../docs/mcp-agents/companion-wattlab-energyplus.md) | Dual-MCP / no IDF in openfdd-mcp |
| [`docs/mcp-agents/dual-site-mcp-it.md`](../../docs/mcp-agents/dual-site-mcp-it.md) | OFDD-MCP-IT A/B/C checklist |
| Playground `vibe_code_apps_20/docs/OPENFDD_ECM_TWINS.md` | ECM twin vs keeper list |
| [`BUILD_CHECKPOINTS.md`](../BUILD_CHECKPOINTS.md) | Milestone + Liberty soak checklist |

**Tip under Liberty turnkey:** playground develop `2323f28` (BUG-ECM-015 + ERV stub).
open-fdd tip advances on merge of PR #601 (was `064eadbc` / `sha-064eadb`).

---

## Vibe 19 — high-level status (2026-07-28)

| Area | Action | Status |
| --- | --- | --- |
| `app/rules/*` (most modules) | SHIM → `open_fdd.rules` | Done |
| `app/rules/runner.py` | SHIM | Done (#59 / UI #580) |
| `app/analytics.py` | SHIM → `open_fdd.analytics.core` | Done |
| `app/rules/custom_registry.py` / `custom_rules.py` | KEEP | Intentional |
| Streamlit / session / demos | KEEP | Intentional |
| Remaining analytics helpers still local under `app/` | Inventory | Phase 3 matrix |
| Reporting twins | Inventory → SHIM/MOVE | Phase 3 |

## Vibe 20 ECM — high-level status

| Area | Action | Status |
| --- | --- | --- |
| 8 parity-proven calcs | DELEGATE via adapter | Done |
| ~18 esco/algorithm keepers | KEEP until Open-FDD twin + parity | Partial |
| EnergyPlus / IDF / Studio | KEEP | Forever (Milestone A) |
| Downloads/tools deltas | Prefer `examples/workspace_tools/` | Partial (#59 seeded pick_best + agent_build) |

## Open-FDD UI

| Area | Action | Status |
| --- | --- | --- |
| Rules / runner / analytics twins | SHIM | Done (#579/#580) |
| Production FDD path | KEEP SQL via central | Forever |
