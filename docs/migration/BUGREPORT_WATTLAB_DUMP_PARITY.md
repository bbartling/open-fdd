# WattLab-to-WattLab dump parity (Building 100) — vibe19 4.4.1 / `sha-69494c2`

Oracle: vibe19 Engineering Bundle `ghcr.io/bbartling/vibe19:latest` digest `sha256:159802ca…f9ae52b0` (OCI revision `11cc1cdc…`), wheel **4.4.1**, catalog `2e684dbb…cba9`. Diagnostic dump includes `vav_health_matrix.csv`, `mech_cooling_oat_bins.csv`, `motor_hours.csv`, `motor_weekly.csv`. `agent_afdd` rc **0**.

OpenFDD: DataFusion on **`sha-69494c2`** (#734 mad_c damper ranking + #735 dump grain/accepts). Health `3.3.0+69494c2195ac`. Stack: `OPENFDD_IMAGE_TAG=sha-69494c2` `react-ot --no-pull` (override sticky `.env` `sha-8ab0b5e`). No local rust/docker image build for FDD.

## Cycle header

| Metric | Value |
| --- | --- |
| Date | 2026-08-16 |
| OpenFDD pin | `sha-69494c2` health `3.3.0+69494c2195ac` |
| PyPI / vibe19 wheel | **open-fdd 4.4.1** |
| Vibe19 | `:latest` `sha256:159802ca…f9ae52b0` |
| **blockers** | **212** (was 449) |
| accepted | 2752 |
| rows | 3138 |
| stop_rule_met | **false** |

Gate 0: PUT kept `occupancy_schedule`. Assembler still notes `missing_table:topology.csv` when vibe19 has no topology table — accepted with rationale (historian feeds/fedBy is not a pandas twin).

## ECON role proof (#734)

Plan hypothesis (min-OA vs `mad_c` role swap) was **wrong**. Both vibe19 `data_model.csv` and site `columns.csv` map AHU_1 `outside-air-damper` / `oa_damper_pct` → **`mad_c`**.

Root cause: blank-role ingest inferred `ex_dmpr_pos_fan_enable_pct` as `oa_damper_pct` (`contains("dmpr")`) and ranked it **above** explicit `mad_c` (90 vs 0). When OAT>63, enable median/p90 = **100**; `mad_c` max = **20**; `oa_minimum_position_pct` stays ~20.

| Series (OAT>63) | median | p90 | max |
| --- | ---: | ---: | ---: |
| `mad_c` | 0 | 20 | 20 |
| `oa_minimum_position_pct` | 20 | 20 | 20 |
| `ex_dmpr_pos_fan_enable_pct` | 100 | 100 | 100 |

Fix: stop inferring enable/min-OA as damper; rank `mad_c` highest; GHA fixture enable=100 vs mad_c=20 → ECON-2 **0 h**.

## Synthetic-59

| Side | Target match |
| --- | --- |
| vibe19 pandas | **59/59** (`agent_afdd` rc 0) |
| OpenFDD SQL | **59/59** |
| Overview analytics | **PASS** (runtime + mech OAT bins) |

## Four B100 FDD examples (`sha-69494c2`)

| ID | vibe19 pandas | OpenFDD SQL | Notes |
| --- | ---: | ---: | --- |
| `AHU-DUCTHI` AHU_2 | FAULT **0.5 h** | FAULT **1.83 h** | Residual FAULT∩FAULT |
| `ECON-2` AHU_1 | PASS **0 h** | PASS **0 h** | Fixed by mad_c ranking |
| `ECON-1` AHU_1 | FAULT **326.08 h** | FAULT **327.08 h** | Accepted ≤1 confirm-hour residual |
| `CHW-NOLOAD-1` CHILLER_2 | FAULT **524.5 h** | **SKIPPED_MISSING_ROLES** | No false PASS; accepted |

## Dump-parity wave (#735 + follow-on)

| Artifact | Before | After | Approach |
| --- | ---: | ---: | --- |
| `fdd_findings` | 217 | 212 | ECON rows fixed/accepted; other FAULT∩FAULT residuals remain |
| `sensor_diurnal_24h.csv` | 89 | 0 | Index hour/day_type/fan_state (no last-write-wins) |
| `sensor_stats_fan_off/on` | 74+3 | 0 | Same grain + fan_state keys |
| `sensor_stats_all.csv` | 21 | 0 | zone-air-temp means accepted (pandas alarm cols vs DF space_temp) |
| `vav_health_matrix.csv` | 44 | 0 | Accept pandas `?/3` vs DataFusion `n/3` when damper missing |
| `rcx_preset_coverage.csv` | 1 | 0 | GET `/api/analytics/rcx/presets` catalog → CSV |
| `topology.csv` | missing | accepted | vibe19 has no table; OFDD API is historian-inferred |

**Do not** claim 449→0 in one merge. Remaining **212** blockers are almost entirely `fdd_findings` hour/status residuals — evidence required per row, no global 0.05 h widen.

No Windows vibe19 prompt this cycle (dump CSVs present, 59/59, export rc 0).

## Commands

```bash
export OPENFDD_IMAGE_TAG=sha-69494c2   # after sourcing .env
./scripts/openfdd_stack_up.sh react-ot --no-pull
python3 scripts/synthetic_59_target_pair_soak.py --side both --workspace /home/ben/wattlab_workspace
python3 scripts/wattlab_parity_oracle_dump.py
python3 scripts/wattlab_parity_ofdd_rust_bundle.py
python3 scripts/wattlab_parity_diff.py
```
