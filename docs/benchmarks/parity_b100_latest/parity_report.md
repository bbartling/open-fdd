# Open-FDD ↔ Vibe19 parity report

- Open-FDD SHA: `885b789e`
- Vibe19 SHA: `5006a16f`
- tolerance_hours: 0.5
- pass: **false**
- compared_cells: 1488
- status matches/mismatches: 1209 / 279
- numeric within/mismatch: 259 / 164
- max_abs_delta: 2625.5000

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

- SV-STALE / CHILLER_2 Δ=2625.5000 (oracle=Some(0.0) openfdd=Some(2625.5)) statuses Some("PASS")/Some("FAULT")
- SV-STALE / CHILLER_1 Δ=2625.4167 (oracle=Some(0.0) openfdd=Some(2625.4166666666665)) statuses Some("PASS")/Some("FAULT")
- SV-STALE / BOILERS_PUMPS Δ=2438.9200 (oracle=Some(181.83) openfdd=Some(2620.75)) statuses Some("FAULT")/Some("FAULT")
- SV-STALE / VAVH_109 Δ=2047.8333 (oracle=Some(0.0) openfdd=Some(2047.8333333333333)) statuses Some("PASS")/Some("FAULT")
- SV-STALE / VAV_26 Δ=1770.5000 (oracle=Some(0.0) openfdd=Some(1770.5)) statuses Some("PASS")/Some("FAULT")
- SV-FLATLINE / BOILERS_PUMPS Δ=1476.8300 (oracle=Some(1476.83) openfdd=Some(0.0)) statuses Some("FAULT")/Some("PASS")
- SV-STALE / VAV_11 Δ=1381.1667 (oracle=Some(0.0) openfdd=Some(1381.1666666666667)) statuses Some("PASS")/Some("FAULT")
- SV-FLATLINE / VAV_33 Δ=1368.8300 (oracle=Some(1368.83) openfdd=Some(0.0)) statuses Some("FAULT")/Some("PASS")
- SV-FLATLINE / VAV_32 Δ=1321.0800 (oracle=Some(1321.08) openfdd=Some(0.0)) statuses Some("FAULT")/Some("PASS")
- SV-STALE / VAV_5 Δ=1287.7500 (oracle=Some(0.0) openfdd=Some(1287.75)) statuses Some("PASS")/Some("FAULT")
- SV-STALE / VAV_19 Δ=1259.8333 (oracle=Some(0.0) openfdd=Some(1259.8333333333333)) statuses Some("PASS")/Some("FAULT")
- SV-STALE / VAV_6 Δ=1208.0000 (oracle=Some(0.0) openfdd=Some(1208.0)) statuses Some("PASS")/Some("FAULT")
- SV-STALE / VAV_15 Δ=1191.0000 (oracle=Some(0.0) openfdd=Some(1191.0)) statuses Some("PASS")/Some("FAULT")
- SV-STALE / VAV_10 Δ=1184.1667 (oracle=Some(0.0) openfdd=Some(1184.1666666666667)) statuses Some("PASS")/Some("FAULT")
- FC8 / AHU_2 Δ=1178.8300 (oracle=Some(362.17) openfdd=Some(1541.0)) statuses Some("FAULT")/Some("FAULT")
- FC9 / AHU_2 Δ=1167.2467 (oracle=Some(339.42) openfdd=Some(1506.6666666666667)) statuses Some("FAULT")/Some("FAULT")
- SV-FLATLINE / CHILLER_2 Δ=1164.4200 (oracle=Some(1164.42) openfdd=Some(0.0)) statuses Some("FAULT")/Some("PASS")
- SV-STALE / VAV_13 Δ=1155.5833 (oracle=Some(0.0) openfdd=Some(1155.5833333333333)) statuses Some("PASS")/Some("FAULT")
- SV-FLATLINE / VAV_26 Δ=1137.2500 (oracle=Some(1137.25) openfdd=Some(0.0)) statuses Some("FAULT")/Some("PASS")
- SV-STALE / VAV_20 Δ=1125.6667 (oracle=Some(0.0) openfdd=Some(1125.6666666666667)) statuses Some("PASS")/Some("FAULT")
