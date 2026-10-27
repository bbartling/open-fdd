# ADR-010: Timescale hard cutover (Wave-X 3.6.0)

**Status:** Accepted (2026-10-12). Supersedes product use of DataFusion-first
([datafusion-first.md](datafusion-first.md)) and Parquet-as-canonical historian
for the Open-FDD product path. Soft-OPEN ≠ FQ.

**4.0 portal note:** decision item 3 below (fieldbus → MQTTS → central) is
superseded on the product path. Ingest is the Normal Framework portal API and
CSV. Fieldbus and MQTTS are an unqualified archive (`archive/ot-edge/`).
Timescale remains the historian. This note does not withdraw the Timescale
decision. The retired transport steps are
`historical/non-executable` in
[`docs/archive/ai-agent/historical-3.5-ot-ops.md`](../archive/ai-agent/historical-3.5-ot-ops.md).

**Timescale-only mandate (2026-10, extends decision 1):** **Timescale/PostgreSQL
only, one canonical telemetry write path, no dual record writing.** Parquet,
Apache Arrow, Arrow IPC, Feather and DataFusion are prohibited in active product
storage, caching, execution and dependencies — not only on the historian path.
Derived FDD / analytics results persist in PostgreSQL or bounded memory. NF
portal REST, NF LAN gRPC (per-site `transport`) and CSV share one validated, idempotent Timescale
telemetry writer. Canonical text:
[`openfdd_agent_spec/DATA_CONTRACT.md` § Storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory).

**BPS reference (pattern only):** ADR 0009 in BPS
(`docs/spec/ADR/0009-timescale-sql-fdd.md`) — Timescale + `.sql` FDD; pandas
oracle test-only. BPS is Haystack-only; Open-FDD is not.

## Decision

1. **Sole product historian + FDD engine** = PostgreSQL + TimescaleDB + versioned
   `sql/fdd/*.sql`. No dual-write. No Parquet / Arrow / DataFusion on the product
   request or ingest path after 3.6.0.
2. **Rust BPS-shaped core** — thin `openfdd-central` (JWT + analytics/FDD → SQL),
   same React SPA. Not a Python port of BPS.
3. **Edge drivers unchanged** — keep `openfdd-fieldbus` BACnet + Modbus. Path:
   fieldbus → MQTTS → central ingest → **Timescale only**.
4. **Haystack optional** — BPS-like optional collector/profile; not required for
   Soft-OPEN seed (warehouse zip + BUILDING_50 package).
5. **Pandas `open_fdd.rules` + DuckDB** — test/oracle only; never product runtime.
6. **VERSION = 3.6.0** (architecture minor). Rollback = git revert / prior GHCR
   sha — not a DF fallback flag.

## Consequences

- Compose requires `openfdd-timescale`; auto-seed applies schema, loads SQL pack,
  imports BUILDING_50 into Timescale.
- Product crates must not open `SessionContext` or write Parquet historian parts
  on the live path. Under the Timescale-only mandate they also must not write
  Parquet / Arrow / Feather result caches or depend on those crates. Oracle/CI may still use pandas/DuckDB harnesses outside the
  product containers.
- SPA Overview / RCx / FDD / Inspect envelopes stay; backend becomes SQL.

## Links

- Plan: `.cursor/plans/timescale_sql_warehouse_greenfield_explore_20261012.plan.md`
- Schema: `sql/schema/`
- Rules pack: `sql/fdd/`
