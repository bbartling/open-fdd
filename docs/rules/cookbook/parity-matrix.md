---
title: Parity matrix
parent: Rule Cookbook
nav_order: 6
---

# SQL ↔ Pandas parity matrix

**Contract:** machine-readable inventory at [`sql_rules/generated/parity_inventory.yaml`](../../../sql_rules/generated/parity_inventory.yaml) (`parity-inventory-v2`).  
Regenerate with `python3 scripts/generate_parity_inventory.py`. Drift fails CI via `--check`.

**Audit:** 2026-08-07 — legacy building-100 / cookbook-port parity labels removed.  
**Audit:** 2026-08-11 — flat `matrix[]` columns (title, roles, proof, thresholds, docs, tests, difference class).

## Why 62 versus 66 (do not pad)

| Surface | Count | Source |
|---------|------:|------|
| Pandas diagnostics | **62** | `CookbookRule(...)` in `open_fdd/rules/cookbook_catalog.py` (`CANONICAL_RULE_COUNT`) |
| SQL twins of those 62 | 62 | `sql_rules/registry.yaml` |
| SQL-only analytics | **4** | `FAN-RUNTIME-HOURS`, `AVG-ZONE-TEMP`, `ZONE-COMFORT-PCT`, `FAULT-ELAPSED-HOURS` |
| SQL registry total | **66** | 62 diagnostics + 4 analytics |

Aliases are **not** extra rules: `SV-SLEW` → `SV-RATE`, `FC13` → `FC13-SAT-HIGH`, `excess_runtime` → `SCHED-1`.

Building 100 `48 × 62` is the pandas diagnostic cartesian product, not 66.

Product UI is **React** (`frontend/web`). Do not delete pandas because SQL exists. Do not put pandas on the product request path.

## Honesty first — parity levels

`parity_status` / inventory `parity_level` is the only machine-readable claim. Cookbook prose must not outrun it.

| Level | Meaning |
|-------|---------|
| `concept_only` | Identity exists; SQL and/or roles incomplete |
| `sql_screening` | SQL compiles and may run; **not** proven mask/duration vs pandas |
| `predicate_parity` | Raw fault predicate matches oracle on fixtures |
| `mask_parity` | Gate + confirmed mask matches oracle |
| `duration_parity` | Fault hours / intervals match within tolerance |
| `site_soak` | Reproducible multi-building soak evidence |

**Wave 0 default:** all former production parity claims were **downgraded** to `sql_screening` (or `concept_only` for `FC7`) until executable oracle fixtures justify a higher level.

**Do not claim “54 full parity.”** That figure was aspirational catalog coverage, not mask-level SQL↔Pandas agreement.

Oracle harness: `crates/fdd_rules` fixtures under `crates/fdd_rules/fixtures/oracle/` + Rust tests (`econ4_confirm_test.rs`, `oracle_parity_test.rs`). CI pandas seeds: `scripts/sql_pandas_oracle_check.py`.

---

## Current registry snapshot (Wave 0)

See generated inventory for exact per-rule rows. Typical tip after Wave 0:

| Level | Approx count |
|-------|-------------:|
| `sql_screening` | 62 |
| `concept_only` | 1 (`FC7`) |
| `predicate_parity`+ | 0 until Wave 1+ proofs land |

### Screening honesty (SV / FC4 / PID / P0 backlog)

Rust screening fixtures may exist for `SV-*`, `FC4`, `PID-HUNT-1`, etc., but they prove **SQL screening semantics only**. Keep `sql_screening` until pandas↔DF fixtures pass at `predicate_parity` / `mask_parity` / `duration_parity`.

P0 correctness backlog (Wave 1): `SV-STALE`, `FC2`, `FC4`, `FC6`, `FC14`/`FC15`, `MECH-OAT-1`, `TRIM-1`, `SCHED-247`, `CHW-NOLOAD-1`, `ECON-1`.

---

## Family coverage (catalog presence, not oracle)

| Family | IDs in registry | SQL file | Pandas cookbook | Oracle-proven? |
|--------|-----------------|:--------:|:---------------:|:--------------:|
| sensor | SV-* | ✅ | ✅ | screening |
| control | PID-HUNT-1, FC4 | ✅ | ✅ | screening |
| ahu | FC*, AHU-*, ECON-*, … | ✅ | ✅ | screening (Wave 0) |
| vav | VAV-* | ✅ | ✅ | screening |
| plant | CHW-*, CW-*, … | ✅ | ✅ | screening |
| trim | TRIM-* | ✅ | ✅ | screening |
| schedule | SCHED-1, SCHED-247 | ✅ | ✅ | screening |

---

## Backend-specific caveats

| Topic | DataFusion SQL | Pandas |
|-------|----------------|--------|
| Window / rolling | `LAG()`, limited `OVER` | `.shift()`, `.rolling()`, multi-sensor sweeps |
| Confirmation | streak / interval (Wave 2 target) | `confirm_fault()` |
| Sensor sweeps | Per-column CASE examples | Catalog `sensor_sweep=True` |
| Control hunting | Screening thresholds | Full TV / reversal / cycle metrics |

---

## Parity test procedure

1. Regenerate inventory: `python3 scripts/generate_parity_inventory.py`
2. Contract gate: `python3 scripts/parity_inventory_check.py`
3. Pandas seed oracle: `pip install -e '.[oracle]' && python3 scripts/sql_pandas_oracle_check.py`
4. Docs smoke: `python3 scripts/cookbook_parity_check.py --all`
5. Rust DF fixtures: `cargo test -p fdd_rules`
6. Promote `parity_level` only when fixtures pass — never by docs alone

Ownership: [`docs/COOKBOOK_OWNERSHIP.md`](../../COOKBOOK_OWNERSHIP.md).
