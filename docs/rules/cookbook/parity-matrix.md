---
title: Parity matrix
parent: Rule Cookbook
nav_order: 6
---

# SQL ↔ Pandas parity matrix

**Audit date:** 2026-07-19 · **Registry source:** `sql_rules/registry.yaml` · **Target:** zero silent drift

## Honesty first

`parity_status` in the registry is the only machine-readable claim. Cookbook prose must not outrun it.

| `parity_status` | Count (registry) | Meaning |
|-----------------|-----------------:|---------|
| `proven_building_100` | 18 | Exercised against BUILDING_100-style fixtures / production soak with matching fault-hour intent |
| `ported_from_cookbook` | 44 | SQL exists and compiles; **ported ≠ oracle-proven**. Mask / confirm / rolling behavior may still diverge from Pandas |
| `skipped_missing_roles` | 1 | `FC7` — skipped until required roles are modeled |

**Do not claim “54 full parity.”** That figure was aspirational catalog coverage, not mask-level SQL↔Pandas agreement.

Oracle harness (phase 1, #550): `crates/fdd_rules` mask/fault-hour fixtures patterned on `econ4_confirm_test.rs`. A rule may only move to `proven_building_100` after a passing oracle (or documented BUILDING_100 soak) — never by docs alone.

---

## Proven vs ported (high level)

### `proven_building_100` (18)

`AVG-ZONE-TEMP`, `ECON-1`, `ECON-2`, `ECON-4`, `FAN-RUNTIME-HOURS`, `FAULT-ELAPSED-HOURS`, `FC1`, `FC2`, `FC3`, `FC8`, `FC9`, `FC10`, `FC11`, `FC12`, `FC13-SAT-HIGH`, `OAT-METEO`, `VAV-1`, `ZONE-COMFORT-PCT`

### Representative `ported_from_cookbook` risk set (phase-1 oracle focus)

These are the mismatch classes called out in #550 — SQL is present; treat results as screening until fixtures pass:

| Family | Rule IDs | Typical drift |
|--------|----------|---------------|
| sensor | `SV-RANGE`, `SV-FLATLINE`, `SV-SPIKE`, `SV-STALE`, `SV-RATE` | Rolling / multi-sensor / rate context simplified in SQL |
| control | `PID-HUNT-1`, `FC4` | Hunting metrics screening vs full TV/reversal |
| ahu | `FC6`, `FC14`, `FC15`, `MECH-OAT-1`, … | Mix / coil / mech enable gates |
| vav | `VAV-4`, `VAV-7`, … | Rolling “fixed high” / high-min SP incomplete in SQL |
| plant | `CHW-NOLOAD-1`, … | Load proxies simplified |
| trim / schedule | `TRIM-*`, `SCHED-1`, `SCHED-247` | Confirm + occupancy semantics |

---

## Family coverage (catalog presence, not oracle)

| Family | IDs in registry | SQL file | Pandas cookbook | Oracle-proven? |
|--------|-----------------|:--------:|:---------------:|:--------------:|
| sensor | SV-* | ✅ | ✅ | mostly **ported** |
| control | PID-HUNT-1 | ✅* | ✅ | **ported** |
| ahu | FC*, AHU-*, ECON-*, OAT-METEO, MECH-OAT-1, … | ✅ | ✅ | mixed |
| vav | VAV-1, VAV-3–5, VAV-7, VAV-REHEAT, VAV-AHU-LEAVE | ✅ | ✅ | mixed (`VAV-1` proven) |
| plant | CHW-*, CW-*, … | ✅ | ✅ | **ported** |
| trim | TRIM-1/3/4 | ✅ | ✅ | **ported** |
| schedule | SCHED-1, SCHED-247 | ✅ | ✅ | **ported** (confirm fixtures landing) |

\* SQL often ships a **screening** variant; see per-rule caveats in the SQL cookbook.

---

## Backend-specific caveats

| Topic | DataFusion SQL | Pandas |
|-------|----------------|--------|
| Window / rolling | `LAG()`, limited `OVER` | `.shift()`, `.rolling()`, multi-sensor sweeps |
| Confirmation | `CONFIRM_ROWS` streak (pandas-equivalent grouping) | `confirm_fault()` |
| Sensor sweeps | Per-column CASE examples | Catalog `sensor_sweep=True` across roles |
| Control hunting | Screening thresholds | Full TV / reversal / cycle metrics (`PID-HUNT-1`) |

---

## Parity test procedure

1. Prefer Rust oracle fixtures in `crates/fdd_rules` (mask / `fault_hours` vs pandas-equivalent reference).
2. Export `telemetry_pivot` window from edge historian when debugging site data.
3. Run SQL via registry runner / `POST /api/fdd/run` (typed params only).
4. Run Pandas mask offline from vibe19 / cookbook compute.
5. Optional docs integrity: `scripts/cookbook_parity_check.py --all` (pandas “any fault” smoke — **not** a full SQL oracle).

See [benchmark strategy](benchmark-strategy.html).
