---
name: openfdd-sql-fdd
description: >-
  Use when working on production Timescale SQL FDD: sql/fdd registry, central
  /api/fdd/run, parity with the pandas oracle, no pandas in central. Triggers on:
  sql/fdd, registry.yaml, FDD engine, SQL cookbook, confirm_min.
---

# Production SQL FDD

`architecture_epoch: portal-timescale-v1`.

- Registry: `sql/fdd/registry.yaml`
- Rules: `sql/fdd/postgres/rules/*.sql`
- Engine: openfdd-central on Timescale / PostgreSQL
- Expression record: `docs/rules/cookbook/` (the file `sql-cookbook.md` is not a DataFusion runner)
- Architecture: `docs/architecture/adr-010-timescale-hard-cutover.md`

`sql_rules/` is the retired DataFusion pack (historical). New product rules go in `sql/fdd`, not there.

Storage mandate: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([`DATA_CONTRACT.md` § Storage mandate](../../DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)). Rule results persist in PostgreSQL or bounded memory — never a Parquet, Arrow or Feather file, and never DataFusion execution.

## Result identity

One FDD result is `fdd_tsdb::FddResultIdentity`: data revision, model revision, rule parameters, pack version, half-open window, quality policy, and schedule policy. The sample writer advances the data revision and stores `fdd_tsdb::ChangedRange` only when a sample row is inserted, corrected at the same timestamp, or removed. An identical replay does not. Read them with `current_data_revision` and `changed_ranges_after`. Do not detect a change with a sum, a count, or `max(ts)`. SCHED-1 occupancy for that identity is `sched1_unoccupied` (numeric values at or below 0.05, plus the unoccupied token family). This API does not run incremental FDD.

## Typed unit and time contract

- **Processing storage is canonical SI (`metric-c-v2`).** Values are normalized once at ingest by the single Timescale writer from engineer-declared source units. SQL rules and the pandas oracle read stored SI; display preference converts at the API/UI boundary only — never query-time imperial admission or a second stored copy per rule.
- Timestamps are UTC `timestamptz`. Fault duration uses the forward timestamp delta. A gap longer than `MAX_GAP_HOURS` (default 1) is unknown: not fault time, not covered time, and it breaks the confirmation streak. The last sample does not add a trailing interval.
- Run one authorized tenant and building at a time. Equipment selection is `equipType` / roles, then exact id. Never a prefix or `LIKE` on `equipment_id`.

## Hard rules

1. Never add silent pandas fallback in central.
2. New production rules need a PostgreSQL file under `sql/fdd/postgres/rules/`, a `sql/fdd/registry.yaml` row, a cookbook row, and a parity row.
3. The pandas oracle may differ. Document that in the parity and gap matrices. Do not paper over it.
4. The UI production path calls central REST, not a local pandas runner.
5. Series overlay (`/api/fdd/.../series`) must honor Lab/`session_config` `confirm_min` and typed params the same way `/api/fdd/run` does.
6. **SCHED-1:** numeric/`false` unoccupied and the string `unoccupied` (and related tokens). Keep `sql/fdd/postgres/rules/sched1_unoccupied_runtime.sql` aligned with pandas `sched1` in `open_fdd/rules/cookbook_catalog.py`.

## Skill home

`openfdd_agent_spec/skills/` is the only authoring tree. Do not create a parallel copy under `.cursor/skills/`, `.claude/skills/`, `.agents/skills/`, or a home directory. Sync with [`scripts/openfdd_install_agent_skills.sh`](../../../scripts/openfdd_install_agent_skills.sh) (`--sync`, optional `--user`). Orientation: [`openfdd_agent_spec/AGENTS.md`](../../AGENTS.md) and the repo [`AGENTS.md`](../../../AGENTS.md).

## Related skills

- [`openfdd-cookbook-parity`](../openfdd-cookbook-parity/SKILL.md) — pandas twin of the same rules
- [`openfdd-architecture`](../openfdd-architecture/SKILL.md) — engine boundaries
- [`openfdd-package-mapping`](../openfdd-package-mapping/SKILL.md) — roles the SQL expects
- [`openfdd-rcx-fdd-plot-poll`](../openfdd-rcx-fdd-plot-poll/SKILL.md) — plots that stay empty
