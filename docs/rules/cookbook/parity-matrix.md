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

| Topic | DataFusion SQL | Pandas |
|-------|----------------|--------|
| Window functions | `LAG()`, `OVER` | `.shift()`, `.rolling()` |
| Confirmation | API `confirmation_seconds` | `confirm_fault()` |
| CTRL-2 hunting | Simplified SQL variant | Full rolling reversal count |

---

## Parity test procedure

1. Export `telemetry_pivot` window from edge historian
2. Run SQL via `POST /api/fdd-rules/{id}/test-sql`
3. Run matching Pandas mask offline
4. Run fixture suite: `scripts/cookbook_parity_check.py --all`

See [benchmark strategy](benchmark-strategy.html).
