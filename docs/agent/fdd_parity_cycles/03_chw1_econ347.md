# Cycle 3 — CHW-1 hours + remaining econ (3/4/6/7) proof-first

Execute after [02_vav_ingest.md](02_vav_ingest.md). One GHA-only product PR **after** a written proof pack. Do **not** wait for GHCR / `:nightly`.

## Hypothesis

Dump leftover:

| Family | n | Shape |
| --- | ---: | --- |
| CHW-1 | 1 | Both FAULT; **217 vs 767 h** — not a status flip |
| ECON-3/4/6/7 | ~8 | Mix of hours and status after `#734` mad_c fix |
| ECON-2 AHU_2 | 1 | 140.58 vs 140.83 (0.25 h) if cycle 1 deferred it |

CHW-1 SQL: [`sql_rules/chw1_low_dt.sql`](../../../sql_rules/chw1_low_dt.sql). Hours diverge by hundreds — likely confirm window, ΔT column choice, or fan/pump gate — **not** a CAST/`ELSE 1` mass-edit.

ECON-3/4/6/7: roles may still bind the wrong analog (mixed-air, OA fraction, cooling-enable) even though OA damper is `mad_c`. **Proof pack first** (column names on AHU_1/AHU_2 vs SQL `AS` roles), then one mapping or SQL PR. Do not guess from B100 hour tables.

CAST / `>= 1.5` is already in economizer SQL — keep it. Do not mass-edit `ELSE 1`.

## Proof pack (required before code)

For each leftover pair, write (in the PR description or a short note under this folder, not a new soak report):

1. Pandas inputs: which vibe19 `data_model.csv` points feed the rule.
2. SQL roles: which `columns.rs` / rank winner lands in the SQL `AS` name.
3. One sentence: missing column vs competing column vs confirm/streak vs true semantic gap.

If the pack says **semantic gap**, stop and leave a `semantic_gap` rationale — do not streak-tune hours to fake a match.

## Files a later agent may change

- [`sql_rules/chw1_low_dt.sql`](../../../sql_rules/chw1_low_dt.sql)
- Remaining `sql_rules/econ*.sql` for ECON-3/4/6/7 (one gate or one role per rule, not a sweep)
- Ingest rank only if the proof pack shows a mad_c-class miss
- [`crates/fdd_rules/src/oracle_parity_test.rs`](../../../crates/fdd_rules/src/oracle_parity_test.rs)
- Optional one-line accept for ECON-2 AHU_2 0.25 h with rationale

Do **not** edit pandas thresholds. Do **not** rewrite B100 bugreports in this PR.

## Tests (synthetic + GHA)

Follow the [shared contract](00_INDEX.md#shared-test-contract-every-cycle).

1. **GHA CHW-1:** short fixture with the proven ΔT/gate mismatch at tiny hours (`pandas_confirm_fault_hours`). Not 217 vs 767.
2. **GHA ECON-3/4/6/7:** one competing-column or missing-role fixture per rule that the proof pack names. Skip rules the pack marks `semantic_gap`.
3. Synthetic-59 **59/59**.

## Do not GHCR

Merge = squash after **Rust CI**. No nightly. Soak later only if requested.

## Out of scope

- SV all-sensor port (cycle 4)
- SCHED-247 window vs streak (cycle 5)
- Mass CAST / `ELSE 1`
- `stop_rule_met=true`
