# SV sensor sweep: pandas catalog vs SQL five-role leftover

Cycle 4. Pandas does **not** iterate every historian column. It sweeps
`SENSOR_LIMITS` / `SWEEP_SENSOR_ROLES` in `open_fdd/rules/cookbook_catalog.py`
(11 roles). SQL used to window only five air temps (`oa_t`, `mat`, `zone_t`,
`rat`, `sat`). Extra catalog analogs (CHWS/CHWR, HWS/HWR, OA humidity, duct
static) faulted in pandas and stayed silent in SQL — the bulk of the dump
leftover ~122 SV-* rows.

## Ported (still `sql_screening`)

`sv_stale.sql`, `sv_flatline.sql`, `sv_range.sql`, and `sv_spike.sql` now
window that catalog:

| Role | STALE (AND) | FLATLINE (OR) | RANGE | SPIKE |
| --- | --- | --- | --- | --- |
| `oa_t` / `mat` / `zone_t` / `rat` / `sat` | yes | yes | yes | yes |
| `chw_supply_t` / `chw_return_t` | yes | yes | yes | yes |
| `hw_supply_t` / `hw_return_t` | yes | yes | yes | yes |
| `oa_h` | yes | yes | yes | yes |
| `duct_static` | no | no | yes | yes |

Duct static is excluded from stale/flatline (`_NO_FLATLINE_ROLES`) because it
legitimately rests near 0 when the fan is off. Humidity and pressure limits
are **not** temperature-scaled (`RANGE_SCALE_TEMPERATURE` applies to temps).

GHA (6 samples × 5 min, `confirm_rows=2`):

- **SV-FLATLINE two-column:** five air temps changing, `oa_h` stuck → SQL
  matches pandas tiny hours (OR).
- **SV-STALE five-role healthy:** all five air temps changing → SQL 0.
- **SV-STALE AND twin:** five temps frozen, `oa_h` live → SQL 0.

Do **not** flip `parity_status` to `proven` from B100 hours. Liberty OFDD-065
stays **WIDE**. A later soak is the only way to see dump 122 → N.

## Remaining `semantic_gap`: SV-RATE

Pandas `ROLE_TO_PROFILE` (`open_fdd/rules/sensor_rate_profiles.py`) has 30+
quantity/location slew limits (`steady_fault_per_hour` per profile). SQL
`sv_rate.sql` still windows five air temps against one `STEADY_FAULT_PER_HOUR`.
Leave `sql_screening`. Do not expand that file to 30 profiles in this cycle.

GHA `sv_rate_humidity_slew_stays_silent` documents SQL 0 on an extra analog
slew. Dump pairs for SV-* must **not** be auto-accepted in
`scripts/wattlab_parity_diff.py` / `tests/test_wattlab_parity_diff.py`.
