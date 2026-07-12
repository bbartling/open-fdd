# Issue #482 / PR #493 — Rule inventory audit

Generated from repository files + Vibe19 local checkout
(`C:\Users\ben\Documents\py-bacnet-stacks-playground\vibe_code_apps_19`).

**Do not trust prose counts.** Counts below are from files.

## Authoritative answers

| Question | Answer |
|----------|--------|
| Canonical 50 for issue #482 | Open-FDD `docs/rules/cookbook/operational-gates.md` numbered list (OG50). |
| PID-HUNT-1 | **Additive #51**, not one of the 50. |
| Vibe19 canonical | **53** rules in `cookbook_catalog.py` / `configs/rule_inventory.yaml` (marketing still says “50”). |
| True FDD vs other (Vibe19) | 45 mechanical/control FDD + 4 sensor-sweep + 1 control-sweep (PID-HUNT-1) + 3 TRIM advisories = 53. |
| Open-FDD registry today | **20** (`sql_rules/registry.yaml` + 20 `*.sql`). |
| OG50 ∩ registry | **15** |
| Analytics in registry (not OG50) | 4: `FAN-RUNTIME-HOURS`, `AVG-ZONE-TEMP`, `ZONE-COMFORT-PCT`, `FAULT-ELAPSED-HOURS` |
| Toward #482 | Need **35** more OG50 production SQL/registry entries (or reconcile ID aliases), keep PID-HUNT-1 as 51st. |

### Canonical OG50 (+51)

1–4 `SV-RANGE`, `SV-FLATLINE`, `SV-SPIKE`, `SV-STALE`  
5 `SV-4`  
6–20 `FC1`–`FC15`  
21–23 `AHU-SATDEV`, `AHU-DUCTHI`, `AHU-SIMUL-HEAT-COOL`  
24–28 `ECON-1`–`ECON-5`  
29–30 `OA-1`, `DMP-1`  
31–36 `VAV-1`, `VAV-3`, `VAV-4`, `VAV-5`, `VAV-7`, `VAV-REHEAT-STUCK`  
37–40 `CHW-1`–`CHW-4`  
41 `HP-1`  
42–44 `WX-1`, `WX-2`, `OAT-METEO`  
45–47 `TRIM-1`, `TRIM-3`, `TRIM-4`  
48–50 `SCHED-1`, `CMD-1`, `VLV-1`  
**51** `PID-HUNT-1`

### Alias friction (OG ↔ cookbook ↔ Vibe19)

| OG / registry | Cookbook / Vibe19 note |
|---------------|------------------------|
| `SV-RANGE` | Vibe19 same; cookbook may use `SV-1`/`SV-2`/`SV-3` |
| `SV-FLATLINE` | cookbook `SV-6` |
| `SV-SPIKE` | cookbook `SV-7` |
| `SV-STALE` | cookbook `SV-5` |
| `AHU-SATDEV` | aux `SAT_DEVIATION*` |
| `AHU-DUCTHI` | aux `DUCT_STATIC_HIGH` |
| `AHU-SIMUL-HEAT-COOL` | aux `HEAT_COOL_SIMULT*` |
| `VAV-REHEAT-STUCK` | likely cookbook `VAV-6` |
| `FC13` | registry id `FC13-SAT-HIGH` |
| Vibe19 `CW-OPT-1`/`CW-APR-1`/`CW-FAN-1` | not in OG50; cookbook has extras beyond 50 |

### Registry today (20)

| rule_id | In OG50? | sql | notes |
|---------|----------|-----|-------|
| FAN-RUNTIME-HOURS | N | Y | analytics |
| VAV-1 | Y | Y | |
| AVG-ZONE-TEMP | N | Y | analytics |
| ZONE-COMFORT-PCT | N | Y | analytics |
| FAULT-ELAPSED-HOURS | N | Y | analytics |
| OAT-METEO | Y | Y | no ### cookbook section |
| FC13-SAT-HIGH | Y (as FC13) | Y | |
| ECON-2 | Y | Y | |
| FC1–FC3, FC7–FC12 | Y | Y | |
| ECON-1, ECON-4 | Y | Y | |
| PID-HUNT-1 | #51 | Y | `parity_status: cookbook_defined` |

### Missing OG50 production SQL (35)

`SV-RANGE`, `SV-FLATLINE`, `SV-SPIKE`, `SV-STALE`, `SV-4`,
`FC4`, `FC5`, `FC6`, `FC14`, `FC15`,
`AHU-SATDEV`, `AHU-DUCTHI`, `AHU-SIMUL-HEAT-COOL`,
`ECON-3`, `ECON-5`,
`OA-1`, `DMP-1`,
`VAV-3`, `VAV-4`, `VAV-5`, `VAV-7`, `VAV-REHEAT-STUCK`,
`CHW-1`–`CHW-4`, `HP-1`,
`WX-1`, `WX-2`,
`TRIM-1`, `TRIM-3`, `TRIM-4`,
`SCHED-1`, `CMD-1`, `VLV-1`

### BUILDING_100 applicability (preliminary)

| Bucket | Rules | Fixture strategy |
|--------|-------|------------------|
| Likely runnable on B100 AHU/VAV roles | FC*, ECON-*, VAV-1, OAT-METEO, OA-1, DMP-1, CMD-1, SCHED-1, SV-* (if sensors mapped) | BUILDING_100 + synthetic edges |
| Plant / HP / CW | CHW-*, HP-1, TRIM-3/4 | **synthetic fixtures** (B100 lacks plant roles) |
| Control sweep | PID-HUNT-1 | synthetic AO time series |
| Advisories | TRIM-* | synthetic or skip-with-contract |

### PR #493 review findings (13 CodeRabbit) — fix queue

1. Gate mode vs predicate conflation (docs/schema)
2. PID SQL status claims vs aggregate-only output
3. Unused `low_extreme_pct` / `high_extreme_pct` → remove
4. SQL clip control_output to [0,100]
5. `loop_enabled` null parity (Pandas vs SQL)
6. Reversal counting ffill vs LAG
7. Wire `window_minutes` or remove
8. Register `minimum_samples` placeholder
9. Oracle `RULE_KINDS` vs registry `ANY`
10. Hydronic-flow threshold parity
11. Optional `loop_enabled` safe projection
12. Parity-matrix honesty
13. Re-review after fixes

### Decision required (do not quietly change denominator)

1. Keep OG50 as #482 denominator; analytics rollups stay extra, not counted toward 50.
2. PID-HUNT-1 remains #51.
3. Prefer Vibe19 IDs (`SV-RANGE`, …) as production IDs; document cookbook aliases.
4. Vibe19’s 53 vs OG50: exclude Vibe19-only CW-* from #482 unless OG table is amended in docs with explicit justification.

## Source-of-truth hierarchy (this PR)

1. Vibe19 Pandas behavior (discovery)
2. Open-FDD Pandas cookbook/oracle
3. `rule-schema.md` + `registry.yaml`
4. DataFusion SQL
5. Parity tests / benchmarks

## Post-port coverage (file-backed)

| Slice | Count |
|-------|------:|
| OG50 in registry + SQL | **50** |
| PID-HUNT-1 (#51) | **1** |
| Analytics rollups | **4** |
| Registry total | **55** |
| #482 OG50 denominator | **met** (analytics + PID remain additive) |
