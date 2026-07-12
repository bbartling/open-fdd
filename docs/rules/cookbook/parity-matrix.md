---
title: Parity matrix
parent: Rule Cookbook
nav_order: 6
---

# SQL ↔ Pandas parity matrix

**Audit date:** 2026-07-05 (Phase 2a/2b) · **Target:** zero manual drift

## Summary

| Status | Count |
|--------|------:|
| ✅ Full parity (SQL + Pandas + catalog metadata) | 60+ |
| SQL only | 0 |
| Pandas only | 0 |

---

## Phase 2 completions

| Item | Status |
|------|--------|
| P0 rule catalog metadata | ✅ [p0-rule-catalog.html](p0-rule-catalog.html) |
| Full Pandas v2 (VLV-1, DMP-1, PLANT-1, SP-HIGH/LOW) | ✅ |
| P2 rules (VAV-6/7, TOWER-1, CTRL-2, SV-7, OA-2) | ✅ both backends |
| Offline fixture regression | ✅ `python3 scripts/cookbook_parity_check.py --all` |

---

## Backend-specific caveats

| Topic | DataFusion SQL | Pandas | Parity status |
|-------|----------------|--------|---------------|
| Window functions | `LAG()`, `OVER` | `.shift()`, `.rolling()` | aligned pattern |
| Confirmation | `{{CONFIRM_ROWS}}` streak | `confirm_fault()` | aligned |
| CTRL-2 hunting | Simplified SQL variant | Full rolling reversal count | **known gap** |
| PID-HUNT-1 output hunting | Row-window TV/reversals; `LAST_VALUE IGNORE NULLS` ffill; clip `[0,100]`; enable null→disabled | Resample + rolling; ffill reversals; clip; enable null→disabled | **aligned intent**; residual risk: resample vs row window |
| Sensor sweeps (SV-*) | Multi-column OR/AND over fixed roles | Per-sensor iterative sweep | **known approximation** |
| Operational gates in SQL | Often metadata-only until runner applies gate | Gate helpers in runner | **partial** — mode/predicate schema split documented |

Do **not** claim full numerical parity while residual windowing/resample differences remain.

---

## Parity test procedure

1. Export `telemetry_pivot` window from edge historian
2. Run SQL via `POST /api/fdd-rules/{id}/test-sql`
3. Run matching Pandas mask offline
4. Run fixture suite: `scripts/cookbook_parity_check.py --all`

See [benchmark strategy](benchmark-strategy.html).
