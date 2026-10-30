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
| `pid_hunting_proxy.sql` | Preserve the historical 8-unit sample-spread screen by role: temperature `8°F Δ = 4.444444444444445°C`, duct static pressure `8 inH₂O = 1990.72 Pa`, and percent/cmd `8` unchanged. |
| `mv_change_point_daily.sql` | Temperature roles preserve the historical IP predicate in SI: `abs(delta_C) >= max(abs(prev_C − (0°F in °C)) × 0.25, 1°F in °C)`, with origin `−17.77777777777778°C` and minimum delta `0.5555555555555556°C`. Other scalar roles retain their existing `max(abs(prev) × 0.25, 1.0)` predicate. |

These thresholds preserve the pre-cutover physical decisions; they are converted
from legacy native units, not reinterpreted around zero in the SI scale. The IP
parity oracle executes the historical predicates on IP inputs; SI pandas and SQL
use the converted thresholds on canonical values. Source-declared units convert
once in the writer before storage. Display IP remains a read-time presentation
choice and does not change stored values or analytics predicates.

Pandas twins live in `open_fdd/analytics/` (`core.py`, `si_thresholds.py`). JSON
field names may still use `_f` suffixes until W5c display cutover; magnitudes are SI.
