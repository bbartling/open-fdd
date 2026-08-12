---
name: openfdd-sql-fdd
description: >-
  Use when working on production DataFusion SQL FDD: sql_rules registry, central
  /api/fdd/run, parity with pandas oracle, no pandas in central. Triggers on:
  sql_rules, DataFusion, registry.yaml, FDD engine, SQL cookbook.
---

# Production SQL FDD

- Registry: `sql_rules/registry.yaml`
- Engine: openfdd-central DataFusion
- Docs: `docs/rules/cookbook/datafusion-sql-cookbook.md`
- Architecture: `docs/architecture/datafusion-first.md`

## Hard rules

1. Never add silent pandas fallback in central.
2. New production rules need SQL file + registry + cookbook + parity row.
3. Pandas oracle may differ — document in parity/gap matrices; do not paper over.
4. UI production path calls central REST — not local pandas runner for “real” FDD.
5. Series overlay (`/api/fdd/.../series`) must honor Lab/`session_config`
   `confirm_min` and typed params the same way `/api/fdd/run` does (prefer
   session-tuned detail over a stale empty results index when overrides exist).
6. **SCHED-1:** portable occupancy — numeric/`false` unoccupied **and** string
   `unoccupied` tokens; keep `sql_rules/sched1_unoccupied_runtime.sql` aligned
   with pandas `sched1` in `open_fdd/rules/cookbook_catalog.py`.
