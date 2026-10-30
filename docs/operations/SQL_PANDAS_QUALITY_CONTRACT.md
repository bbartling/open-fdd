# SQL ↔ pandas quality contract (#1253, #1284)

Soft-OPEN evidence. Soft-OPEN ≠ FQ. SI (`metric-c-v2`) is canonical for storage and processing. Engineer-declared source units are normalized once by the telemetry writer; user display preference is presentation-only. See [unit contract](../modeling/units.md) and [ADR-012](../architecture/adr-012-si-processing-and-qualification.md).

## Finding

On live plant-pack history (BPS Building 50 / `AHU_1`), **AHU-SATDEV** warehouse
SQL fault hours matched a pandas oracle with `quality=False` exactly. The gap vs
full `open_fdd.rules.run_rule` (`quality=True`) was fully explained by
`open_fdd.quality` nulling `OUT_OF_RANGE` / sentinel samples — **not** by
SAT_DEV_ERR, fan-gate, or confirm equation drift.

## Unit contract and parity chain

Rule and analytics thresholds, samples, and parameters use SI semantic kinds. Never compare an IP baseline with SI values without the explicit parity chain. The qualification order is frozen IP baseline → pandas IP = pandas SI on identical physical frames → pandas SI = SQL SI → post-cutover SQL SI = IP baseline on every site (P3). Fault seconds compare exactly; analytics use the parity harness tolerance. Fixture parity does not establish live P3, and this document does not declare FQ.

## Contract (Soft-OPEN)

| Surface | Quality (`OUT_OF_RANGE` / sentinels) | Contractual for warehouse SQL? |
| --- | --- | --- |
| Timescale / warehouse SQL (`sql/fdd/**`) | **OFF** (raw historian values; SQL has no quality filter) | **Yes — product FDD** |
| Pandas SQL-aligned oracle (equation + gate + confirm, `quality=False`) | **OFF** | **Yes — SQL parity oracle** |
| Full `open_fdd.rules.run_rule` (`quality=True`) | **ON** | **No** — separate surface; hour deltas vs SQL are DIAG only |

## Fail-closed enforcement

- Unit CI: `tests/rules/test_sql_quality_contract.py`
- Live stress: `scripts/stress/08_sql_vs_pandas_sparql.py` — strict SQL ≈ quality-OFF;
  `--allow-satdev-drift` is WARN-only lab emergency (do not weaken default).

Pandas DataFrames for cookbook rules must use **Haystack role column names**
(`discharge-air-temp`, `discharge-air-temp-sp`, `fan-status`, …). Warehouse short
aliases (`sat` / `sat_sp`) are SQL-only and must not silently green pandas parity.

## Longer-term (out of Soft-OPEN)

Port role-aware OUT_OF_RANGE / sentinel filtering into warehouse SQL (or an ingest
quality channel) if product SQL hours should match the default pandas runner on
dirty plant packs. Until then, keep the two surfaces explicit.
