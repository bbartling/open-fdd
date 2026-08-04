"""Psychrometric helpers for web weather (Open-Meteo style) — dew point + wet bulb.

Dew point uses the Magnus-Tetens approximation (simple, good enough for FDD).
Wet bulb uses Stull (2011) empirical formula — accurate enough for RCx scatter/faults
without a full psychrometric library.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def dewpoint_f_from_db_rh(dry_bulb_f: pd.Series | np.ndarray | float, rh_pct: pd.Series | np.ndarray | float) -> pd.Series:
    """Dew point °F from dry-bulb °F and relative humidity % (0–100)."""
    t_f = pd.to_numeric(dry_bulb_f, errors="coerce")
    rh = pd.to_numeric(rh_pct, errors="coerce").clip(0.1, 100.0)
    t_c = (t_f - 32.0) * 5.0 / 9.0
    # Magnus coefficients (Sonntag 1990)
    a, b = 17.625, 243.04
    gamma = np.log(rh / 100.0) + (a * t_c) / (b + t_c)
    dp_c = (b * gamma) / (a - gamma)
    dp_f = dp_c * 9.0 / 5.0 + 32.0
    return pd.Series(dp_f, index=getattr(t_f, "index", None))


def wetbulb_f_stull(dry_bulb_f: pd.Series | np.ndarray | float, rh_pct: pd.Series | np.ndarray | float) -> pd.Series:
    """Wet-bulb °F via Stull (2011) — valid roughly −20…50°C, RH 5–99%."""
    t_f = pd.to_numeric(dry_bulb_f, errors="coerce")
    rh = pd.to_numeric(rh_pct, errors="coerce").clip(5.0, 99.0)
    t_c = (t_f - 32.0) * 5.0 / 9.0
    # Stull JAMC 2011 eq. 1
    tw_c = (
        t_c * np.arctan(0.151977 * np.sqrt(rh + 8.313659))
        + np.arctan(t_c + rh)
        - np.arctan(rh - 1.676331)
        + 0.00391838 * rh ** 1.5 * np.arctan(0.023101 * rh)
        - 4.686035
    )
    tw_f = tw_c * 9.0 / 5.0 + 32.0
    return pd.Series(tw_f, index=getattr(t_f, "index", None))


def enrich_weather_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize Open-Meteo / BAS weather columns and derive dewpoint / wetbulb when possible."""
    if df is None or df.empty:
        return df
    out = df.copy()

    # Dry bulb → wx_oa_t
    if "web-outside-air-temp" not in out.columns:
        for c in (
            "outside_air_temp_f",
            "temperature_2m",
            "temp_f",
            "dry_bulb_f",
            "outside-air-temp",
            "oat",
        ):
            if c in out.columns and out[c].notna().any():
                out = out.rename(columns={c: "web-outside-air-temp"})
                break
        if "web-outside-air-temp" not in out.columns:
            for c in out.columns:
                cl = c.lower()
                if "temp" in cl and "dew" not in cl and "wet" not in cl:
                    out = out.rename(columns={c: "web-outside-air-temp"})
                    break

    # RH → wx_oa_rh
    if "web-outside-air-humidity" not in out.columns:
        for c in ("relative_humidity_2m", "rh", "humidity", "outside_air_humidity", "oa_rh"):
            if c in out.columns and out[c].notna().any():
                out = out.rename(columns={c: "web-outside-air-humidity"})
                break

    # Dewpoint column aliases
    if "web-outside-air-dewpoint" not in out.columns:
        for c in ("dewpoint_2m", "dew_point_f", "dewpoint_f", "oa_dewpoint", "dp_f"):
            if c in out.columns and out[c].notna().any():
                out = out.rename(columns={c: "web-outside-air-dewpoint"})
                break

    # Derive dewpoint from DB + RH when missing
    if "web-outside-air-dewpoint" not in out.columns or out["web-outside-air-dewpoint"].notna().sum() == 0:
        if "web-outside-air-temp" in out.columns and "web-outside-air-humidity" in out.columns:
            out["web-outside-air-dewpoint"] = dewpoint_f_from_db_rh(out["web-outside-air-temp"], out["web-outside-air-humidity"])

    # Wet bulb
    if "web-outside-air-wetbulb" not in out.columns or out["web-outside-air-wetbulb"].notna().sum() == 0:
        if "web-outside-air-temp" in out.columns and "web-outside-air-humidity" in out.columns:
            out["web-outside-air-wetbulb"] = wetbulb_f_stull(out["web-outside-air-temp"], out["web-outside-air-humidity"])

    return out


def prefer_web_oat(
    df: pd.DataFrame,
    weather: pd.DataFrame | None = None,
    *,
    prefer_web: bool = True,
) -> pd.Series | None:
    """Return outdoor dry-bulb series — web weather first when prefer_web (data-model default)."""
    if prefer_web:
        from app.weather_resolver import resolve_effective_oat

        series, _src = resolve_effective_oat(df, weather)
        return series
    order = ("outside-air-temp", "web-outside-air-temp", "bas-outside-air-temp", "oa_t_effective")
    for col in order:
        if col in df.columns and df[col].notna().any():
            return pd.to_numeric(df[col], errors="coerce")
    if weather is not None and not weather.empty:
        wx = weather.reindex(df.index)
        for col in order:
            if col in wx.columns and wx[col].notna().any():
                return pd.to_numeric(wx[col], errors="coerce")
        for col in ("dry_bulb_f", "outside_air_temp_f"):
            if col in wx.columns and wx[col].notna().any():
                return pd.to_numeric(wx[col], errors="coerce")
    return None
