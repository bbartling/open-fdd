"""Quantity-aware unit conversion (no magnitude guessing for percent)."""

from __future__ import annotations

from typing import Literal

PA_PER_IN_WC = 248.84
LPS_PER_CFM = 0.471947
KPA_PER_PSI = 6.894757


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


def admit_temperature_to_pack_f(value: float, source_unit: str | None) -> float:
    """Convert a temperature reading into imperial-f-v1 pack units (°F)."""
    tok = normalize_unit_token(source_unit)
    if tok in {"c", "degc", "celsius"}:
        return celsius_to_fahrenheit(value)
    if tok in {"f", "degf", "fahrenheit", ""}:
        return value
    raise ValueError(f"unknown temperature unit: {source_unit!r}")


def norm_command(
    s,
    *,
    representation: Literal["percent", "fraction"] = "percent",
):
    """Normalize actuator/command values to fraction 0–1.

    ``percent`` means the series is 0–100 (1 → 0.01). ``fraction`` means 0–1
    already (1 → 1.0). Magnitude heuristics are forbidden.
    """
    import pandas as pd

    if s is None:
        return pd.Series(dtype=float)
    num = pd.to_numeric(s, errors="coerce")
    if representation == "fraction":
        return num.astype(float)
    if representation == "percent":
        return num.astype(float) / 100.0
    raise ValueError(f"unknown command representation: {representation!r}")


def series_admit_temp_to_f(values, units=None):
    import numpy as np
    import pandas as pd

    vals = pd.to_numeric(values, errors="coerce")
    if units is None:
        return vals
    out = vals.copy()
    for i, (v, u) in enumerate(zip(vals.tolist(), units.tolist(), strict=False)):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        try:
            out.iloc[i] = admit_temperature_to_pack_f(float(v), None if u is None else str(u))
        except ValueError:
            out.iloc[i] = np.nan
    return out
