# Open-FDD ↔ Vibe19 parity report

- Open-FDD SHA: `cb2827b9`
- Vibe19 SHA: `5006a16f`
- tolerance_hours: 0.5
- pass: **false**
- compared_cells: 1488
- status matches/mismatches: 1211 / 277
- numeric within/mismatch: 266 / 157
- max_abs_delta: 2623.5833

## Comparable rules

- `AHU-DUCTHI` (equivalent_after_normalization)
- `AHU-SATDEV` (equivalent_after_normalization)
- `AHU-SIMUL-HEAT-COOL` (equivalent_after_normalization)
- `CMD-1` (equivalent_after_normalization)
- `DMP-1` (equivalent_after_normalization)
- `ECON-1` (exact_direct_equivalent)
- `ECON-2` (exact_direct_equivalent)
- `ECON-3` (equivalent_after_normalization)
- `ECON-4` (exact_direct_equivalent)
- `FC1` (exact_direct_equivalent)
- `FC10` (exact_direct_equivalent)
- `FC11` (exact_direct_equivalent)
- `FC12` (exact_direct_equivalent)
- `FC13-SAT-HIGH` (exact_direct_equivalent)
- `FC2` (exact_direct_equivalent)
- `FC3` (exact_direct_equivalent)
- `FC4` (equivalent_after_normalization)
- `FC5` (equivalent_after_normalization)
- `FC7` (equivalent_after_normalization)
- `FC8` (exact_direct_equivalent)
- `FC9` (exact_direct_equivalent)
- `HP-1` (equivalent_after_normalization)
- `OA-1` (equivalent_after_normalization)
- `OAT-METEO` (exact_direct_equivalent)
- `SV-FLATLINE` (equivalent_after_normalization)
- `SV-RANGE` (equivalent_after_normalization)
- `SV-SPIKE` (equivalent_after_normalization)
- `SV-STALE` (equivalent_after_normalization)
- `VAV-1` (exact_direct_equivalent)
- `VLV-1` (equivalent_after_normalization)
- `WX-1` (equivalent_after_normalization)

## Worst deltas

- SV-STALE / CHILLER_2 Δ=2623.5833 (oracle=Some(0.0) openfdd=Some(2623.5833333333335)) statuses Some("PASS")/Some("FAULT")
- SV-STALE / CHILLER_1 Δ=2623.5000 (oracle=Some(0.0) openfdd=Some(2623.5)) statuses Some("PASS")/Some("FAULT")
- SV-STALE / BOILERS_PUMPS Δ=2437.0033 (oracle=Some(181.83) openfdd=Some(2618.8333333333335)) statuses Some("FAULT")/Some("FAULT")
- SV-STALE / VAVH_109 Δ=2045.9167 (oracle=Some(0.0) openfdd=Some(2045.9166666666667)) statuses Some("PASS")/Some("FAULT")
- SV-STALE / VAV_26 Δ=1769.7500 (oracle=Some(0.0) openfdd=Some(1769.75)) statuses Some("PASS")/Some("FAULT")
- SV-FLATLINE / BOILERS_PUMPS Δ=1476.8300 (oracle=Some(1476.83) openfdd=Some(0.0)) statuses Some("FAULT")/Some("PASS")
- SV-STALE / VAV_11 Δ=1379.2500 (oracle=Some(0.0) openfdd=Some(1379.25)) statuses Some("PASS")/Some("FAULT")
- SV-FLATLINE / VAV_33 Δ=1368.8300 (oracle=Some(1368.83) openfdd=Some(0.0)) statuses Some("FAULT")/Some("PASS")
- SV-FLATLINE / VAV_32 Δ=1321.0800 (oracle=Some(1321.08) openfdd=Some(0.0)) statuses Some("FAULT")/Some("PASS")
- SV-STALE / VAV_5 Δ=1285.8333 (oracle=Some(0.0) openfdd=Some(1285.8333333333333)) statuses Some("PASS")/Some("FAULT")
- SV-STALE / VAV_19 Δ=1258.0000 (oracle=Some(0.0) openfdd=Some(1258.0)) statuses Some("PASS")/Some("FAULT")
- SV-STALE / VAV_6 Δ=1206.0833 (oracle=Some(0.0) openfdd=Some(1206.0833333333333)) statuses Some("PASS")/Some("FAULT")
- SV-STALE / VAV_15 Δ=1189.6667 (oracle=Some(0.0) openfdd=Some(1189.6666666666667)) statuses Some("PASS")/Some("FAULT")
- SV-STALE / VAV_10 Δ=1182.2500 (oracle=Some(0.0) openfdd=Some(1182.25)) statuses Some("PASS")/Some("FAULT")
- SV-FLATLINE / CHILLER_2 Δ=1164.4200 (oracle=Some(1164.42) openfdd=Some(0.0)) statuses Some("FAULT")/Some("PASS")
- SV-STALE / VAV_13 Δ=1153.7500 (oracle=Some(0.0) openfdd=Some(1153.75)) statuses Some("PASS")/Some("FAULT")
- SV-FLATLINE / VAV_26 Δ=1137.2500 (oracle=Some(1137.25) openfdd=Some(0.0)) statuses Some("FAULT")/Some("PASS")
- SV-STALE / VAV_20 Δ=1124.9167 (oracle=Some(0.0) openfdd=Some(1124.9166666666667)) statuses Some("PASS")/Some("FAULT")
- SV-FLATLINE / AHU_1 Δ=1094.0000 (oracle=Some(1094.0) openfdd=Some(0.0)) statuses Some("FAULT")/Some("PASS")
- SV-STALE / VAV_18 Δ=1089.6667 (oracle=Some(0.0) openfdd=Some(1089.6666666666667)) statuses Some("PASS")/Some("FAULT")
