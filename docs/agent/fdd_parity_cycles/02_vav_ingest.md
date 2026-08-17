# Cycle 2 — VAV damper/flow ingest vs VAV-4/6 PASS 0

Execute after [01_ducthi_satdev_econ2.md](01_ducthi_satdev_econ2.md). One GHA-only product PR. Do **not** wait for GHCR / `:nightly`.

## Hypothesis

Dump leftover: **~55 VAV** rows. Several **VAV-4 / VAV-6** pairs are pandas **FAULT** (~1300–1600 h) vs SQL **PASS 0**. Same shape as the ECON mad_c miss: SQL never sees the analog the pandas rule uses.

[`sql_rules/vav4_damper_full_open.sql`](../../../sql_rules/vav4_damper_full_open.sql) needs `damper_pct`. If ingest in [`crates/fdd_core/src/columns.rs`](../../../crates/fdd_core/src/columns.rs) / [`crates/fdd_core/src/role_rank.rs`](../../../crates/fdd_core/src/role_rank.rs) ranks a competing column (or a blank-role `contains("dmpr")`) above the mapped damper, SQL evaluates empty and reports PASS 0.

VAV-6 airflow analog is the same class of bug (flow role vs competing column).

Synthetic VAV cases already exist in the 59 zip — **keep 59/59**. Do not invent new synthetic expected hours by editing pandas.

**VAV-4 still has fan `ELSE 1`.** This cycle’s product change is **ingest rank**, not the fan-gate. Fan-gate for VAV-4 is a later one-rule follow-on (see [FAN_ON_ELSE_1_FOLLOWON.md](../FAN_ON_ELSE_1_FOLLOWON.md)) — do not mix it in unless the short fixture proves missing-fan is the PASS-0 cause.

## Files a later agent may change

- [`crates/fdd_core/src/columns.rs`](../../../crates/fdd_core/src/columns.rs)
- [`crates/fdd_core/src/role_rank.rs`](../../../crates/fdd_core/src/role_rank.rs) (or equivalent rank table)
- [`sql_rules/vav4_damper_full_open.sql`](../../../sql_rules/vav4_damper_full_open.sql) — only if the mapped column name in SQL does not match ingest
- Sibling VAV-6 flow SQL under `sql_rules/`
- [`crates/fdd_rules/src/oracle_parity_test.rs`](../../../crates/fdd_rules/src/oracle_parity_test.rs) — competing-column fixtures (same style as ECON mad_c vs `ex_dmpr_pos_fan_enable_pct`)

Do **not** edit pandas. Do **not** auto-accept VAV FAULT∩PASS.

## Tests (synthetic + GHA)

Follow the [shared contract](00_INDEX.md#shared-test-contract-every-cycle).

1. **GHA VAV-4 competing damper:** fixture with mapped `damper_pct` (or vibe19 damper column) **and** a higher-ranked junk `*dmpr*` analog that is not the damper. Pandas FAULT on the real damper; SQL must FAULT the same tiny hours — not PASS 0.
2. **GHA VAV-6 competing flow:** same pattern for airflow.
3. Hours: 6 samples × 5 min, `confirm_rows=2`, `pandas_confirm_fault_hours` exact. Not B100 1300 h.
4. Synthetic-59 **59/59**.

## Do not GHCR

Merge = squash after **Rust CI**. No nightly pin. B100 re-diff only on an explicit later soak.

## Out of scope

- CHW-1 / remaining econ (cycle 3)
- SV all-sensor sweep (cycle 4)
- SCHED-247 definition (cycle 5)
- Mass `ELSE 1` / CAST edits
- Promising 212→0
