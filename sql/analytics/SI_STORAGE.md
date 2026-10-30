# Analytics SQL — metric-c-v2 storage (#1284 W4f)

All bodies under `postgres/queries/` assume historian `sample.val` is already in
canonical SI (°C, Δ°C, Pa, kPa, L/s, kW, kWh, percent 0–100). There is no
query-time imperial admit.

Threshold-bearing queries:

| Query | SI parameters |
| --- | --- |
| `economizer_deltas.sql` | `$5` = minimum \|OAT−RAT\| in Δ°C (default 5.556) |
| `mechanical_cooling_oat_bins.sql` | OAT bins at 10 / 15.556 / 21.111 / 26.667 / 32.222 °C |
| `sensor_faults_staleness.sql` | Temperature range −40 … 121.111 °C on `*_t` roles |
| `pid_hunting_proxy.sql` | Role-specific equivalent of legacy threshold 8: 4.444444444444445 °C sample standard deviation for temperature roles; 1990.72 Pa for `dsp`; 8 unchanged for unitless percent commands |
| `mv_change_point_daily.sql` | Temperature roles preserve the legacy 0 °F reference as −17.77777777777778 °C and 1 °F minimum delta as 0.5555555555555556 °C; scalar roles retain the existing comparison |

These are processing-policy equivalents, not qualification claims. In
particular, the change-point temperature predicate remains relative to its
converted legacy origin; it is not redefined relative to 0 °C.

Pandas twins live in `open_fdd/analytics/` (`core.py`, `si_thresholds.py`). JSON
field names may still use `_f` suffixes until W5c display cutover; magnitudes are SI.
