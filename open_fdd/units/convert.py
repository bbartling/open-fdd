"""Unit helpers for ingest/display layers (no magnitude guessing for percent).

The rules themselves are SI only and never call these; they exist for reporting/ingest code.
"""

from __future__ import annotations

from typing import Literal

PA_PER_IN_WC = 248.84
LPS_PER_CFM = 0.471947
KPA_PER_PSI = 6.894757
LPS_PER_GPM = 0.0630902

def normalize_unit_token(unit: str | None) -> str:
    if unit is None:
        return ""
    return (
        str(unit)
        .strip()
        .lower()
        .replace("°", "")
        .replace(" ", "")
        .replace(".", "")
        .replace("_", "")
        .replace("/", "")
    )


def celsius_to_fahrenheit(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def fahrenheit_to_celsius(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


def delta_c_to_delta_f(dc: float) -> float:
    return dc * 9.0 / 5.0


def delta_f_to_delta_c(df: float) -> float:
    return df * 5.0 / 9.0


def source_temperature_to_si(value: float, source_unit: str) -> float:
    """Convert an explicitly declared source temperature to canonical °C."""
    tok = normalize_unit_token(source_unit)
    if tok in {"c", "degc", "celsius"}:
        return float(value)
    if tok in {"f", "degf", "fahrenheit"}:
        return fahrenheit_to_celsius(float(value))
    raise ValueError(f"unknown temperature unit: {source_unit!r}")


def norm_command(
    s,
    *,
    representation: Literal["percent", "fraction", "auto"] = "auto",
):
    """Normalize actuator/command values to fraction 0–1.

    - ``percent``: declared 0–100 (1 → 0.01).
    - ``fraction``: declared 0–1 (1 → 1.0).
    - ``auto``: series-level only — if any finite value is > 1, treat the
      whole series as percent; otherwise leave as fraction. Never use the
      old element-wise ``value <= 1`` passthrough (that mapped 1% → 100%).
    """
    import pandas as pd

    if s is None:
        return pd.Series(dtype=float)
    num = pd.to_numeric(s, errors="coerce").astype(float)
    if representation == "fraction":
        return num
    if representation == "percent":
        return num / 100.0
    if representation == "auto":
        finite = num.dropna()
        if not finite.empty and float(finite.max()) > 1.0:
            return num / 100.0
        return num
    raise ValueError(f"unknown command representation: {representation!r}")


def series_source_temp_to_c(values, units):
    import numpy as np
    import pandas as pd

    vals = pd.to_numeric(values, errors="coerce")
    if units is None:
        raise ValueError("declared source units are required for temperature conversion")
    out = pd.Series(np.nan, index=vals.index, dtype=float)
    for i, (v, u) in enumerate(zip(vals.tolist(), units.tolist(), strict=False)):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        try:
            out.iloc[i] = source_temperature_to_si(float(v), str(u))
        except ValueError:
            out.iloc[i] = np.nan
    return out
