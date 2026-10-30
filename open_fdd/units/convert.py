"""Quantity-aware unit conversion (no magnitude guessing for percent)."""

from __future__ import annotations

from typing import Literal

PA_PER_IN_WC = 248.84
LPS_PER_CFM = 0.471947
KPA_PER_PSI = 6.894757
LPS_PER_GPM = 0.0630902

# Imperial bound unit -> (scale, offset) into canonical SI; offset only for absolute degF.
_IP_TO_SI_BOUND: dict[str, tuple[float, float]] = {
    "degF": (5.0 / 9.0, -32.0 * 5.0 / 9.0),
    "degF_delta": (5.0 / 9.0, 0.0),
    "inH2O": (PA_PER_IN_WC, 0.0),
    "cfm": (LPS_PER_CFM, 0.0),
    "gpm": (LPS_PER_GPM, 0.0),
    "psi": (KPA_PER_PSI, 0.0),
}


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


def ip_bound_to_si(value: float | None, ip_unit: str) -> float | None:
    """Convert one imperial bound into canonical SI (metric-c-v2) storage units.

    ``ip_unit`` must be a declared imperial unit; unknown units raise.
    """
    if value is None:
        return None
    if ip_unit not in _IP_TO_SI_BOUND:
        raise ValueError(f"no SI bound conversion declared for unit {ip_unit!r}")
    scale, offset = _IP_TO_SI_BOUND[ip_unit]
    return float(value) * scale + offset
