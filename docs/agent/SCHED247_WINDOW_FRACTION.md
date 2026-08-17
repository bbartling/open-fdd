# SCHED-247: window `always_on_pct` vs confirm streak

Cycle 5 option **A**. Pandas `_sched247` faults only when `mean(on) ≥ always_on_pct`
over the **whole analysis window**, then returns the on-mask (confirm is applied
after). SQL used to confirm every on-streak regardless of duty cycle.

`sql_rules/sched247_always_on.sql` now gates on `AVG(on_bit)` per equipment.
Ranked proof is unchanged (fan/pump/chiller status, else `fan_cmd`). Pressure
still does not OR into the FAULT mask.

Keep `parity_status: sql_screening`. Do not mark proven from B100 hours. Do not
auto-accept dump PASS vs FAULT in `wattlab_parity_diff.py`.

GHA (6 samples × 5 min, `confirm_rows=2`):

- `sched247_fan_cmd_screening_confirm_streak`: 50% duty with a 3-sample streak
  is below default 0.95 → SQL 0 (pandas).
- `sched247_high_duty_short_streak_matches_pandas`: `always_on_pct=0.5`, 4/6 on,
  longest streak = 2 → SQL matches `pandas_confirm_fault_hours`.
