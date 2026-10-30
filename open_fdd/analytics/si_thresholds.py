"""SI (metric-c-v2) thresholds for analytics SQL and pandas twins (#1284 W4f).

Values match imperial Guideline 36 / legacy limits converted once (absolute °C
with offset, Δ°C scale-only). Field names may still use ``_f`` until W5c display
cutover; stored magnitudes are SI.
"""

from __future__ import annotations

# Guideline 36 economizer mixing: |OAT−RAT| minimum (was 10 °F Δ).
ECON_DIAG_DT_MIN_C = 10.0 * 5.0 / 9.0  # 5.555555555555556

# Mechanical cooling OAT bin edges (imperial 50/60/70/80/90 °F boundaries).
MECH_OAT_BIN_EDGES_C: tuple[float, ...] = (
    10.0,
    15.555555555555556,
    21.11111111111111,
    26.666666666666668,
    32.22222222222222,
)

MECH_OAT_BIN_LABELS: tuple[str, ...] = (
    "<10",
    "10-16",
    "16-21",
    "21-27",
    "27-32",
    ">=32",
)

# Sensor staleness analytics range gate on ``*_t`` roles (was -40 / 250 °F).
SENSOR_TEMP_RANGE_MIN_C = -40.0
SENSOR_TEMP_RANGE_MAX_C = (250.0 - 32.0) * 5.0 / 9.0  # 121.11111111111111

# CHW leave-temp proof ceiling (was 48 °F).
CHW_LEAVE_MAX_C = (48.0 - 32.0) * 5.0 / 9.0  # 8.88888888888889

# Economizer weather summary (was 60 °F OAT).
COLD_OAT_C = (60.0 - 32.0) * 5.0 / 9.0  # 15.555555555555556

# Free-cool opportunity band (Guideline 36: 60 ≤ DB < 72 °F, DP < 60 °F).
ECON_FREE_COOL_DB_MIN_C = (60.0 - 32.0) * 5.0 / 9.0  # 15.555555555555556
ECON_FREE_COOL_DB_MAX_C = (72.0 - 32.0) * 5.0 / 9.0  # 22.22222222222222
ECON_FREE_COOL_DP_MAX_C = (60.0 - 32.0) * 5.0 / 9.0  # 15.555555555555556

# Winter economizer ceiling (was 25 °F web OAT).
FREEZE_OAT_C = (25.0 - 32.0) * 5.0 / 9.0  # -3.888888888888889
