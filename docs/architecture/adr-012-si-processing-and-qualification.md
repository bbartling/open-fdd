# ADR-012: SI processing and qualification evidence

- **Status:** Accepted for the 4.0.7 SI cutover; SI implementation is pending full release qualification.
- **Decision date:** 2026-10-28
- **Related:** #1284, [`metric_units.json`](../../sql/contract/metric_units.json), [unit contract](../modeling/units.md), [SQL/pandas quality contract](../operations/SQL_PANDAS_QUALITY_CONTRACT.md).

## Decision

`metric-c-v2` (°C, Δ°C, Pa/kPa, L/s, kW, kWh, and explicitly distinguished percent/fraction kinds) is the canonical storage and processing ABI. Engineers declare each source point's unit and quantity. One Timescale telemetry writer normalizes supported source values once at ingest; the in-place SI migration normalizes already stored samples. Rules and analytics consume SI. Missing or incompatible declarations fail closed as `unit_undeclared`. IP is not a processing mode after cutover. User display preference is a presentation concern; display-IP conversion is allowed at the API/UI boundary and never changes stored values or rule evaluation.

The product remains a generic, model-driven framework: no building, vendor, or campus behavior is encoded in unit handling. Timescale/PostgreSQL remains the sole telemetry store with one writer and no dual record writes. Python/pandas remains PyPI and qualification tooling, outside the product request path.

## Parity and qualification

Qualification uses the ordered evidence chain:

1. Capture the pre-cutover IP baseline per site (rule/equipment/day fault seconds, analytics rows, sample counts, and declared-unit inventory).
2. Establish pandas IP = pandas SI on identical physical frames.
3. Establish pandas SI = SQL SI on fixtures and SYNTH; fault seconds compare exactly and analytics use the harness's stated tolerance.
4. After live cutover, establish SQL SI = the frozen IP baseline for every site (P3), plus live pandas SI = SQL SI.

**Soft-OPEN** means implementation or a subset of offline evidence exists while required qualification evidence remains open. It may describe a specific surface or gate; it does not imply release qualification. `si-parity` fixture results and P0–P2 do not establish live P3.

**Fully qualified (FQ) is not declared by this ADR or by a documentation, unit, or cookbook check.** For #1284, FQ may be declared only after Wave 9 live P3 passes against the frozen W0c baseline on every site and live P2 matches, with counts and evidence recorded. A mismatch blocks qualification and requires stop/repair or the documented backup restore. Until then status remains Soft-OPEN / qualification pending.

## Consequences

- Cookbook thresholds, schema examples, and parameter metadata use SI and semantic `kind` values.
- IP fixtures/goldens may remain only as frozen qualification test data until the parity chain is complete; they are not product behavior.
- Display conversion remains available and must distinguish absolute values from deltas/rates.
- A release note or checklist cannot upgrade qualification status without the live evidence above.
