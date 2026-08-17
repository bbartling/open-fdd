# Cycle 1 — DUCTHI residual, SATDEV fan-gate, ECON-2 AHU_2 0.25 h

Execute after [00_INDEX.md](00_INDEX.md). One GHA-only product PR. Do **not** wait for GHCR / `:nightly`.

## Hypothesis

Dump leftover (post `#736`, `sha-69494c2`):

| Pair | Pandas | SQL | Notes |
| --- | ---: | ---: | --- |
| AHU-DUCTHI / AHU_2 | 0.5 h FAULT | 1.83 h FAULT | Fan gate already honest in SQL; residual is confirm/window, not `ELSE 1` |
| AHU-SATDEV / (2 AHUs) | ~76 h FAULT | ~76 h FAULT | Both FAULT; hours close enough that the dump still flags if \|Δ\| > 0.05 h **or** SATDEV still invents on-hours when fan cols missing |
| ECON-2 / AHU_2 | 140.58 h | 140.83 h | 0.25 h over the 0.05 h gate. **Not** the mad_c bug (`#734` cleared ECON-2 AHU_1 to 0 h PASS) |

**SATDEV:** [`sql_rules/ahu_satdev.sql`](../../../sql_rules/ahu_satdev.sql) lines 10–13 still `ELSE 1` when fan columns are missing. Pandas treats missing fan as not-on. A GHA fixture with SAT off-setpoint and **no fan cols** must not invent on-hours.

**DUCTHI:** [`sql_rules/ahu_ducthi.sql`](../../../sql_rules/ahu_ducthi.sql) already avoids fan `ELSE 1`. Prove the 0.5 vs 1.83 h residual on a **short** fixture (tiny exact hours), not by soaking B100.

**ECON-2 AHU_2:** fixture-only if you can isolate 0.25 h; otherwise leave until cycle 3 (econ proof pack). Do **not** accept FAULT∩FAULT without a written rationale.

## Files a later agent may change

- [`sql_rules/ahu_satdev.sql`](../../../sql_rules/ahu_satdev.sql) — this cycle’s **one** fan-gate (`ELSE 1` → missing-fan = off). See [FAN_ON_ELSE_1_FOLLOWON.md](../FAN_ON_ELSE_1_FOLLOWON.md). Do **not** mass-edit other rules.
- [`sql_rules/ahu_ducthi.sql`](../../../sql_rules/ahu_ducthi.sql) — only if the short fixture proves a real confirm/window bug.
- [`crates/fdd_rules/src/oracle_parity_test.rs`](../../../crates/fdd_rules/src/oracle_parity_test.rs) — GHA fixtures.
- Optional: one-line accept in [`scripts/wattlab_parity_diff.py`](../../../scripts/wattlab_parity_diff.py) **only** for ECON-2 AHU_2 0.25 h with rationale (rounding / last-interval), not a blanket hour gate.

Do **not** edit pandas thresholds. Do **not** edit [`expected_faults.csv`](../../../reports/wattlab-parity/fixtures/synthetic_59/openfdd_synthetic_59_rule_fixture_v1/expected_faults.csv).

## Tests (synthetic + GHA)

Follow the [shared contract](00_INDEX.md#shared-test-contract-every-cycle).

1. **GHA SATDEV missing-fan:** `write_equipment_fixture` with SAT off-setpoint, **no** `fan_status` / `sfn_c` columns. Expect SQL fault hours **0** (not invented on-hours). 6 samples × 5 min, `confirm_rows=2`.
2. **GHA DUCTHI residual:** short fixture that encodes the 0.5 vs 1.83 pattern at tiny scale (e.g. one extra confirm row vs pandas). Hours must be **tiny and exact** (`pandas_confirm_fault_hours`), not B100 1.83 h.
3. **GHA ECON-2 0.25 h (optional this cycle):** skip unless isolated in ≤6 samples. Else defer to cycle 3.
4. Synthetic-59 soak must stay **59/59**. Do not run `cargo test --all` on Bensbench.

## Do not GHCR

Merge = squash after **Rust CI** (and pytest if Python classifier touched). No `OPENFDD_IMAGE_TAG=nightly`. No pin `sha-<7>`. Soak optional **later** if the user asks.

## Out of scope

- VAV ingest, CHW-1, SV sensor sweep, SCHED-247 (cycles 2–5)
- Mass `ELSE 1` edits
- Windows playground closeout
- Promising dump 212→0
