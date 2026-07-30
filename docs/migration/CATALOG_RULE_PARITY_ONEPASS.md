---
title: Catalog rule parity one-pass (PR D)
parent: Migration
nav_order: 45
---

# Catalog pandas ↔ DataFusion SQL parity — one-pass residuals

**Date:** 2026-07-29 · **Scope:** best-effort alignment; honest residuals — not “all 63 proven.”

Machine-readable claims remain `parity_status` in `sql_rules/registry.yaml`.
This page records the one-pass inventory after SCHED-1 zone-comfort (PR C).

## Inventory (registry)

| `parity_status` | Count | Notes |
|-----------------|------:|-------|
| `proven_building_100` | 24 | Includes SCHED-1 (zone gate + base fallback) |
| `ported_from_cookbook` | 38 | Screening / incomplete pandas match |
| `skipped_missing_roles` | 1 | FC7 |

UI pandas cookbook recipes: **59**. SQL registry: **63**. Dual-catalog banner is intentional.

## High-impact pass results

| Rule | Intent check | SQL vs pandas | Action this pass | Residual |
|------|--------------|---------------|------------------|----------|
| SCHED-1 | Excess runtime when zone satisfied | Zone comfort band when `zone_t` present; base-only when absent/NULL | SQL + optional_roles inject + oracle zone fixture | None for mask intent; Liberty hours still soak |
| SCHED-247 | Always-on | Screening streak ≠ window `always_on_pct` | No flip to proven | Keep ported |
| CHW-NOLOAD-1 | Plant running while load satisfied | Oracle screening fixture already present | Listed; no SQL gap found this pass | Keep ported until plant soak |
| SV-STALE | Stale sensor | Fan-on gate present (OFDD-065) | No further SQL change | Liberty **WIDE** (B50 +2500 / B100 +2728 hrs) |
| VAV-1 | Comfort | Zone-only schema safe (no fan_cmd in SQL) | No change | Liberty **WIDE** (B50 +21k / B100 +17k hrs) |
| SV-RANGE / FLATLINE / SPIKE / RATE | Sensor family | Screening oracles only | No flip | Keep ported |
| FC4 / PID-HUNT-1 | Hunting | Screening oracles only | No flip | Keep ported |
| FC7 | Missing roles | skipped_missing_roles | Untouched | Needs role model |

## Liberty FAULT deltas

Filled from Liberty soak `parity_hunt_20260730T003200Z` (tip `sha-064eadb`). Do **not** flip `proven` from hours alone:

| Rule | Site | pandas h | SQL h | Δ | Status |
|------|------|---------:|------:|--:|--------|
| SV-STALE | B50 | 884 | 3384 | +2500 | **WIDE** |
| SV-STALE | B100 | 543 | 3271 | +2728 | **WIDE** |
| VAV-1 | B50 | 2815 | 24550 | +21735 | **WIDE** |
| VAV-1 | B100 | 3789 | 21615 | +17826 | **WIDE** |
| SCHED-247 | B50 | 0 | 3235 | +3235 | **WIDE** (streak residual) |
| ECON-1 | B50 | 700 | 0.6 | −699 | **WIDE** |
| ECON-2 | B50 | 191 | 3143 | +2952 | **WIDE** |

## Docs discipline

- No vibe-out of `docs/rules/` expression cookbook in this pass.
- Registry description for SCHED-1 updated; migration pages own residual tables.
- Oracle fixtures: `crates/fdd_rules/src/oracle_parity_test.rs`.
