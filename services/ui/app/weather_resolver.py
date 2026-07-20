"""Central outdoor-air temperature source policy for AFDD / RCx.

Policy
------
- Web / Open-Meteo ``web-outside-air-temp`` is PRIMARY for economizer / free-cool, mech-cooling
  OAT bins, RCx scatters, weather-driven analytics, and physics rules that need OAT.
- BAS ``outside-air-temp`` is fallback only when web weather is unavailable.
- When both exist, preserve both — never silently overwrite BAS ``outside-air-temp``.
- Working columns: ``oa_t_effective``, ``oa_t_effective_source`` (``web``|``bas``),
  optional ``bas-outside-air-temp`` (copy of BAS when present).
- OAT-METEO compares real BAS ``outside-air-temp`` vs web ``web-outside-air-temp`` only when both exist.
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from app.weather_psychrometrics import enrich_weather_frame

OatSource = Literal["web", "bas"]


def has_web_oat(df: pd.DataFrame | None) -> bool:
    if df is None or df.empty:
        return False
    return "web-outside-air-temp" in df.columns and bool(df["web-outside-air-temp"].notna().any())


def has_bas_oat(df: pd.DataFrame | None) -> bool:
    """True when a real BAS outdoor-air sensor series is present (not web-injected)."""
    if df is None or df.empty:
        return False
    if "has_bas_oat" in df.attrs:
        return bool(df.attrs["has_bas_oat"])
    if "bas-outside-air-temp" in df.columns and bool(df["bas-outside-air-temp"].notna().any()):
        return True
    return False


def resolve_effective_oat(
    df: pd.DataFrame,
    weather: pd.DataFrame | None = None,
) -> tuple[pd.Series | None, OatSource | None]:
    """Return (effective OAT series, source) preferring web over BAS."""
    if df is None or df.empty:
        return None, None
    if has_web_oat(df):
        return pd.to_numeric(df["web-outside-air-temp"], errors="coerce"), "web"
    if weather is not None and not weather.empty:
        wx = enrich_weather_frame(weather).reindex(df.index)
        if has_web_oat(wx):
            return pd.to_numeric(wx["web-outside-air-temp"], errors="coerce"), "web"
        for col in ("dry_bulb_f", "outside_air_temp_f"):
            if col in wx.columns and wx[col].notna().any():
                return pd.to_numeric(wx[col], errors="coerce"), "web"
    if "bas-outside-air-temp" in df.columns and df["bas-outside-air-temp"].notna().any():
        return pd.to_numeric(df["bas-outside-air-temp"], errors="coerce"), "bas"
    if "outside-air-temp" in df.columns and df["outside-air-temp"].notna().any():
        return pd.to_numeric(df["outside-air-temp"], errors="coerce"), "bas"
    return None, None


def apply_effective_oat_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``oa_t_effective`` / source / ``bas_oa_t`` without overwriting BAS ``outside-air-temp``."""
    if df is None or df.empty:
        return df
    out = df.copy()
    bas_present = "outside-air-temp" in out.columns and bool(out["outside-air-temp"].notna().any())
    if bas_present:
        out["bas-outside-air-temp"] = pd.to_numeric(out["outside-air-temp"], errors="coerce")
    web_present = has_web_oat(out)
    if web_present:
        out["oa_t_effective"] = pd.to_numeric(out["web-outside-air-temp"], errors="coerce")
        source: OatSource | None = "web"
    elif bas_present:
        out["oa_t_effective"] = pd.to_numeric(out["outside-air-temp"], errors="coerce")
        source = "bas"
    else:
        source = None
    out.attrs["oa_t_effective_source"] = source
    out.attrs["has_web_weather"] = web_present
    out.attrs["has_bas_oat"] = bas_present
    if source is not None:
        out["oa_t_effective_source"] = source
    return out


def inject_oa_t_for_physics(df: pd.DataFrame) -> pd.DataFrame:
    """If BAS ``outside-air-temp`` missing, copy ``oa_t_effective`` into working ``oa_t``.

    Never used for OAT-METEO. Does not overwrite a real BAS series.
    """
    if df is None or df.empty:
        return df
    if has_bas_oat(df):
        return df
    if "oa_t_effective" not in df.columns or not bool(df["oa_t_effective"].notna().any()):
        return df
    out = df.copy()
    out["outside-air-temp"] = pd.to_numeric(out["oa_t_effective"], errors="coerce")
    out.attrs["oa_t_injected_from"] = out.attrs.get("oa_t_effective_source") or "web"
    return out


def oat_meteo_availability(df: pd.DataFrame) -> tuple[bool, list[str]]:
    """Return (ok, missing_reasons) for BAS-vs-web compare — both real sources required."""
    missing: list[str] = []
    if not has_bas_oat(df):
        missing.append("bas outside-air-temp (required for sensor vs web compare)")
    if not has_web_oat(df):
        missing.append("web-outside-air-temp (web weather)")
    return (len(missing) == 0), missing


def weather_source_metrics(df: pd.DataFrame) -> dict[str, Any]:
    """Metrics block for rule results / run reports."""
    src = df.attrs.get("oa_t_effective_source")
    if src is None and "oa_t_effective_source" in df.columns:
        val = df["oa_t_effective_source"].dropna()
        src = str(val.iloc[0]) if len(val) else None
    has_web = bool(df.attrs.get("has_web_weather", has_web_oat(df)))
    has_bas = has_bas_oat(df)
    metrics: dict[str, Any] = {
        "weather_source": src,
        "has_web_weather": has_web,
        "has_bas_oat": has_bas,
        "oa_t_source": src,
    }
    if has_bas and has_web:
        bas_col = "bas-outside-air-temp" if "bas-outside-air-temp" in df.columns else "outside-air-temp"
        bas = pd.to_numeric(df[bas_col], errors="coerce")
        web = pd.to_numeric(df["web-outside-air-temp"], errors="coerce")
        diff = (bas - web).abs().dropna()
        if len(diff):
            metrics["oat_meteo_mean_abs_diff_f"] = round(float(diff.mean()), 3)
            metrics["oat_meteo_max_abs_diff_f"] = round(float(diff.max()), 3)
    return metrics
