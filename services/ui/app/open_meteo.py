"""Open-Meteo historical weather fetch for vibe19 model-seed / FDD.

Ports the TADCO sidecar historical-forecast fetch into a Streamlit-safe module.
Network calls are optional — callers should catch exceptions; tests mock HTTP.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from app.weather_psychrometrics import enrich_weather_frame

HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

# Hourly vars useful for both FDD and AMY EPW generation
HOURLY_VARS = (
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "surface_pressure",
    "shortwave_radiation",
    "direct_normal_irradiance",
    "diffuse_radiation",
)

MINUTELY_15_VARS = (
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "wind_speed_10m",
)


def dew_point_f_from_rh(temp_f: float, rh_pct: float) -> float:
    """Magnus approximation; inputs °F and % RH, output °F."""
    if rh_pct <= 0 or pd.isna(temp_f) or pd.isna(rh_pct):
        return float("nan")
    tc = (temp_f - 32.0) * 5.0 / 9.0
    rh = max(min(rh_pct, 100.0), 0.01)
    a = math.log(rh / 100.0) + (17.625 * tc) / (243.04 + tc)
    td_c = (243.04 * a) / (17.625 - a)
    return td_c * 9.0 / 5.0 + 32.0


def _as_date_str(value: date | datetime | str | pd.Timestamp) -> str:
    if isinstance(value, str):
        return value[:10]
    if isinstance(value, pd.Timestamp):
        return value.tz_convert("UTC").strftime("%Y-%m-%d") if value.tzinfo else value.strftime("%Y-%m-%d")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d")
    return value.isoformat()


def geocode(name: str, *, session: Any = None) -> tuple[float, float, str]:
    """Return (lat, lon, label) for a place name via Open-Meteo geocoding."""
    import requests

    http = session or requests
    r = http.get(GEOCODE_URL, params={"name": name, "count": 1}, timeout=30)
    r.raise_for_status()
    results = r.json().get("results") or []
    if not results:
        raise ValueError(f"Geocoding found no results for: {name}")
    hit = results[0]
    label = f"{hit.get('name')}, {hit.get('admin1')}, {hit.get('country')}"
    return float(hit["latitude"]), float(hit["longitude"]), label


def fetch_open_meteo(
    lat: float,
    lon: float,
    start: date | datetime | str | pd.Timestamp,
    end: date | datetime | str | pd.Timestamp,
    *,
    grid_minutes: int = 60,
    session: Any = None,
    timeout: int = 120,
) -> pd.DataFrame:
    """Fetch Open-Meteo historical weather and return an enriched frame.

    When ``grid_minutes`` <= 15, uses minutely_15 (temp/RH/dew/wind only).
    Otherwise uses hourly (includes solar radiation for EPW generation).

    Output has DatetimeIndex (UTC) and canonical ``web-outside-air-*`` columns
    via ``enrich_weather_frame``. Extra columns (solar, pressure, wind) retained.
    """
    import requests

    http = session or requests
    start_s = _as_date_str(start)
    end_s = _as_date_str(end)
    use_15 = int(grid_minutes) <= 15

    params: dict[str, Any] = {
        "latitude": float(lat),
        "longitude": float(lon),
        "start_date": start_s,
        "end_date": end_s,
        "timezone": "UTC",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "pressure_unit": "hPa",
    }
    if use_15:
        params["minutely_15"] = ",".join(MINUTELY_15_VARS)
        block_key = "minutely_15"
    else:
        params["hourly"] = ",".join(HOURLY_VARS)
        block_key = "hourly"

    r = http.get(HISTORICAL_FORECAST_URL, params=params, timeout=timeout)
    r.raise_for_status()
    payload = r.json()
    block = payload.get(block_key)
    if not block or not block.get("time"):
        reason = payload.get("reason") or payload.get("error") or "no data"
        raise ValueError(f"Open-Meteo returned no {block_key} data: {reason}")

    raw = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(block["time"], utc=True),
            "dry_bulb_f": block.get("temperature_2m"),
            "relative_humidity_pct": block.get("relative_humidity_2m"),
            "dew_point_f": block.get("dew_point_2m"),
            "wind_speed_mph": block.get("wind_speed_10m"),
        }
    )
    if block.get("wind_direction_10m") is not None:
        raw["wind_direction_deg"] = block.get("wind_direction_10m")
    if block.get("surface_pressure") is not None:
        raw["surface_pressure_hpa"] = block.get("surface_pressure")
    if block.get("shortwave_radiation") is not None:
        raw["shortwave_radiation_wm2"] = block.get("shortwave_radiation")
    if block.get("direct_normal_irradiance") is not None:
        raw["direct_normal_irradiance_wm2"] = block.get("direct_normal_irradiance")
    if block.get("diffuse_radiation") is not None:
        raw["diffuse_radiation_wm2"] = block.get("diffuse_radiation")

    raw = raw.sort_values("timestamp_utc").drop_duplicates("timestamp_utc")
    # Fill missing dew point via Magnus
    if raw["dew_point_f"].isna().any():
        mask = raw["dew_point_f"].isna()
        raw.loc[mask, "dew_point_f"] = [
            dew_point_f_from_rh(t, rh)
            for t, rh in zip(
                raw.loc[mask, "dry_bulb_f"].tolist(),
                raw.loc[mask, "relative_humidity_pct"].tolist(),
            )
        ]

    raw = raw.set_index("timestamp_utc")
    enriched = enrich_weather_frame(raw.reset_index())
    # Keep DatetimeIndex for analytics join
    if "timestamp_utc" in enriched.columns:
        enriched = enriched.set_index("timestamp_utc")
    enriched.attrs["open_meteo"] = {
        "lat": float(lat),
        "lon": float(lon),
        "start": start_s,
        "end": end_s,
        "grid_minutes": int(grid_minutes),
        "block": block_key,
        "fetched_utc": datetime.now(timezone.utc).isoformat(),
    }
    return enriched


def align_to_index(weather: pd.DataFrame, grid: pd.DatetimeIndex) -> pd.DataFrame:
    """Interpolate weather onto an exact DatetimeIndex (HVAC historian grid)."""
    if weather is None or weather.empty:
        return weather
    src = weather.copy()
    if not isinstance(src.index, pd.DatetimeIndex):
        if "timestamp_utc" in src.columns:
            src = src.set_index(pd.to_datetime(src["timestamp_utc"], utc=True))
            src = src.drop(columns=["timestamp_utc"], errors="ignore")
        else:
            raise ValueError("weather must have DatetimeIndex or timestamp_utc column")
    if src.index.tz is None:
        src.index = src.index.tz_localize("UTC")
    else:
        src.index = src.index.tz_convert("UTC")
    grid = grid.tz_convert("UTC") if grid.tz is not None else grid.tz_localize("UTC")
    combined = src.index.union(grid)
    wide = src.reindex(combined).sort_index()
    for c in wide.columns:
        if pd.api.types.is_numeric_dtype(wide[c]):
            wide[c] = pd.to_numeric(wide[c], errors="coerce").interpolate(
                method="time", limit_direction="both"
            )
    out = wide.reindex(grid)
    if hasattr(weather, "attrs"):
        out.attrs.update(getattr(weather, "attrs", {}) or {})
    return out


__all__ = [
    "fetch_open_meteo",
    "geocode",
    "align_to_index",
    "dew_point_f_from_rh",
    "HISTORICAL_FORECAST_URL",
    "GEOCODE_URL",
]
