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

Pandas twins live in `open_fdd/analytics/` (`core.py`, `si_thresholds.py`). JSON
field names may still use `_f` suffixes until W5c display cutover; magnitudes are SI.
