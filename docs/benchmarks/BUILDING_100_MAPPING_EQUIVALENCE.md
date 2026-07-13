# Building 100 mapping-equivalence report

**Generated:** 2026-07-13 (Phase 1 convergence)
**Open-FDD SHA:** see PR #493 HEAD
**Vibe19 SHA:** `5006a16f`
**Dataset:** private `hvac_systems_CLEANED/BUILDING_100` (not committed)

## Purpose

Separate **engine defects** from **mapping / input-contract mismatches** before
claiming numeric parity on Building 100.

## Proven equivalent (process)

| Dimension | Open-FDD | Vibe19 | Result |
| --- | --- | --- | --- |
| Source tree | validate + ingest of BUILDING_100 | same private tree | equivalent |
| Equipment IDs | parquet `equipment_id` | frame keys | equivalent |
| Poll interval | 300 s from manifest | attrs / infer | equivalent |
| Timezone | UTC timestamps | UTC | equivalent |
| Rule registry IDs | 55 SQL registry | OG50 + extras | partial overlap (see parity_summary) |
| Operational RUN gate | SQL inject + startup | `active_mask` | equivalent for FC family after gate fix |
| Confirmation | SQL lagged streak | pandas confirm | equivalent on fixtures |

## SV-STALE plant / VAV deltas — classification

Parity artifact: `docs/benchmarks/parity_b100_latest/parity_details.csv`

| Equipment class | Typical Δ fault_hours | Classification | Notes |
| --- | --- | --- | --- |
| AHU_1 / AHU_2 | ~0.003 h | **exact equivalent** | Presence fix + same sensors |
| CHILLER_*, BOILERS_PUMPS | ~2400–2624 h | **mapping mismatch / not comparable** | Open-FDD history maps enable/setpoint-like points into modeled sensor roles (`oa_t`, `chw_supply_t`, …) that stay flat → FAULT. Vibe19 PASS uses a different modeled-sensor set for those units. |
| Many VAV_* | ~185–2045 h | **mapping mismatch / not comparable** until role hygiene | Same class of false sensor membership / wrong physical column → role |

**Do not enlarge hour tolerance to hide these.** Fix mapping (column_map / role inference) or exclude from comparable set with an explicit `not_comparable` class in the overlap matrix.

## Overlap matrix (Phase 1)

| Open-FDD output | Vibe19 output | Comparison type | Result |
| --- | --- | --- | --- |
| Registry FDD rules (comparable subset) | `rule_digest` / oracle CSVs | equivalent after normalization | partial — see `parity_summary.json` |
| `motor_hours` | `motor_hours.csv` | exact (small golden) | **PASS** |
| `motor_weekly` | `motor_weekly.csv` | exact (small golden) | **PASS** |
| `mech_cooling_oat_bins` | `mech_cooling_oat_bins.csv` | exact (small golden) | **PASS** |
| Analytics rollups FAN-RUNTIME-HOURS etc. | (FDD rule slots) | Open-FDD-only | not FAULT/PASS comparable |
| `rcx_preset_*` | RCx coverage/digests | Vibe19-only until Rust RCx port | remaining |
| `rule_digest` small golden | Vibe19 digest | equivalent after status vocab | remaining full wire-up |

## Next mapping actions

1. Emit per-equipment role inventory for BUILDING_100 (committed sample only — no private CSVs).
2. For SV-STALE, restrict modeled sensors to roles that Vibe19 `_sweep_stale` actually evaluates for that equipment type.
3. Re-run `openfdd_cli parity` and require unexplained mismatches → tiny fixture + fix.
