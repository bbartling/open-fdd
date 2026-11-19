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

from open_fdd.analytics.weather_psychrometrics import enrich_weather_frame

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


#: BAS vs web outdoor-air band (delta degC), the dashboard's BAS_BAND_C.
BAS_WEB_BAND_C = 2.0


def default_web_max_age_seconds(bas: pd.Series, web: pd.Series) -> float:
    """As-of age limit for the web reading: max(1.5 x median web interval, 2 x median BAS interval), in seconds.

    The dashboard derives the same limit from the web cadence and its grid step; here the BAS cadence is the grid.
    """
    def median_step(s: pd.Series) -> float:
        idx = pd.DatetimeIndex(s.dropna().index).sort_values()
        if len(idx) < 2:
            return 0.0
        return float(pd.Series(idx[1:] - idx[:-1]).dt.total_seconds().median())

    return max(1.5 * median_step(web), 2.0 * median_step(bas))


def bas_vs_web_oat_stats(
    bas: pd.Series,
    web: pd.Series,
    *,
    max_age_seconds: float | None = None,
    band_c: float = BAS_WEB_BAND_C,
) -> dict[str, Any]:
    """BAS minus web outdoor-air temperature, web joined as-of to each BAS sample (degC; delta degC).

    A BAS sample is paired with the latest web reading at or before it that is at most ``max_age_seconds`` old (default
    :func:`default_web_max_age_seconds`); unpaired samples are not assessed. Returns n, bias (mean delta), mae, max_abs
    and within_band (share of |delta| <= ``band_c``); the statistics are None when n is 0. The SQL twin is
    ``sql/analytics/bas_vs_web_oat.sql``.
    """
    b = pd.to_numeric(bas, errors="coerce").dropna().sort_index()
    w = pd.to_numeric(web, errors="coerce").dropna().sort_index()
    age = default_web_max_age_seconds(b, w) if max_age_seconds is None else float(max_age_seconds)
    out: dict[str, Any] = {"n": 0, "bias": None, "mae": None, "max_abs": None, "within_band": None,
                           "max_age_seconds": age, "band_c": float(band_c)}
    if b.empty or w.empty:
        return out
    left = pd.DataFrame({"t": pd.DatetimeIndex(b.index), "bas": b.to_numpy(dtype=float)})
    right = pd.DataFrame({"t": pd.DatetimeIndex(w.index), "web": w.to_numpy(dtype=float)})
    joined = pd.merge_asof(left, right, on="t", direction="backward",
                           tolerance=pd.Timedelta(seconds=age), allow_exact_matches=True)
    d = (joined["bas"] - joined["web"]).dropna()
    if d.empty:
        return out
    out.update(n=int(len(d)), bias=float(d.mean()), mae=float(d.abs().mean()), max_abs=float(d.abs().max()),
               within_band=float((d.abs() <= float(band_c)).mean()))
    return out
