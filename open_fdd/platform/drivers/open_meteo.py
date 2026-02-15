"""
Open-Meteo driver: fetch historical weather, write to timeseries_readings.

Configurable interval (e.g. once per day). Used for FDD rules that need OAT.
Includes solar/radiation, cloud cover, wind direction for load modeling and analysis.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import uuid

import numpy as np
import pandas as pd
import requests
from psycopg2.extras import execute_values

from open_fdd.platform.database import get_conn

WEATHER_POINTS = [
    "temp_f",
    "rh_pct",
    "dewpoint_f",
    "wind_mph",
    "gust_mph",
    "wind_dir_deg",
    "shortwave_wm2",
    "direct_wm2",
    "diffuse_wm2",
    "gti_wm2",
    "cloud_pct",
]
OPEN_METEO_FIELDS = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "global_tilted_irradiance",
    "cloud_cover",
]
COLUMN_MAP = {
    "temperature_2m": "temp_f",
    "relative_humidity_2m": "rh_pct",
    "dew_point_2m": "dewpoint_f",
    "wind_speed_10m": "wind_mph",
    "wind_direction_10m": "wind_dir_deg",
    "wind_gusts_10m": "gust_mph",
    "shortwave_radiation": "shortwave_wm2",
    "direct_radiation": "direct_wm2",
    "diffuse_radiation": "diffuse_wm2",
    "global_tilted_irradiance": "gti_wm2",
    "cloud_cover": "cloud_pct",
}


def _get_hourly_array(hourly: dict, key: str, n: int) -> Optional[np.ndarray]:
    """Return numpy array for hourly key if present, else None."""
    if key not in hourly:
        return None
    return np.array(hourly[key], dtype=float)


def _c_to_f(c: np.ndarray) -> np.ndarray:
    """Convert Celsius to Fahrenheit."""
    return c * 9.0 / 5.0 + 32.0


def fetch_open_meteo(
    lat: float,
    lon: float,
    start_date: date,
    end_date: date,
    timezone: str = "America/Chicago",
    base_url: str = "https://archive-api.open-meteo.com/v1/era5",
) -> pd.DataFrame:
    """Fetch hourly weather from Open-Meteo ERA5 archive. Includes temp, RH, dew point,
    wind, solar/radiation, and cloud cover."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "hourly": ",".join(OPEN_METEO_FIELDS),
        "timezone": timezone,
    }
    resp = requests.get(base_url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        raise RuntimeError("No hourly.time in Open-Meteo response.")
    n = len(times)

    tz = ZoneInfo(timezone)
    ts = pd.to_datetime(times)
    if ts.tz is None:
        ts = ts.tz_localize(tz)
    else:
        ts = ts.tz_convert(tz)
    df = pd.DataFrame({"ts": ts})

    # Core (required): API returns °C, km/h; we convert to °F, mph for BAS consistency
    temp_c = _get_hourly_array(hourly, "temperature_2m", n)
    rh = _get_hourly_array(hourly, "relative_humidity_2m", n)
    if temp_c is None or rh is None:
        raise RuntimeError("temperature_2m and relative_humidity_2m are required.")
    df["temp_f"] = np.round(_c_to_f(temp_c), 2)
    df["rh_pct"] = np.round(rh.astype(float), 2)

    # Dew point (prefer API; fallback to Magnus formula from temp_c + rh)
    dew_c = _get_hourly_array(hourly, "dew_point_2m", n)
    if dew_c is not None:
        df["dewpoint_f"] = np.round(_c_to_f(dew_c), 2)
    else:
        a, b = 17.27, 237.7
        alpha = (a * temp_c) / (b + temp_c) + np.log(np.clip(rh / 100.0, 1e-6, 100))
        dew_calc = (b * alpha) / (a - alpha)
        df["dewpoint_f"] = np.round(_c_to_f(dew_calc), 2)

    # Wind: API returns km/h; convert to mph (km/h * 0.621371 ≈ mph, or m/s * 2.237)
    wind_speed = _get_hourly_array(hourly, "wind_speed_10m", n)
    wind_gust = _get_hourly_array(hourly, "wind_gusts_10m", n)
    wind_dir = _get_hourly_array(hourly, "wind_direction_10m", n)
    KMH_TO_MPH = 0.621371
    if wind_speed is not None:
        df["wind_mph"] = np.round(wind_speed * KMH_TO_MPH, 2)
    if wind_gust is not None:
        df["gust_mph"] = np.round(wind_gust * KMH_TO_MPH, 2)
    if wind_dir is not None:
        df["wind_dir_deg"] = np.round(wind_dir, 1)

    # Solar/radiation (W/m²) — no conversion
    for api_key, col in [
        ("shortwave_radiation", "shortwave_wm2"),
        ("direct_radiation", "direct_wm2"),
        ("diffuse_radiation", "diffuse_wm2"),
        ("global_tilted_irradiance", "gti_wm2"),
    ]:
        arr = _get_hourly_array(hourly, api_key, n)
        if arr is not None:
            df[col] = np.round(arr.astype(float), 2)

    # Cloud cover (%)
    cloud = _get_hourly_array(hourly, "cloud_cover", n)
    if cloud is not None:
        df["cloud_pct"] = np.round(cloud, 2)

    return df


def store_weather_for_site(
    site_id: uuid.UUID,
    df: pd.DataFrame,
) -> dict:
    """
    Store weather DataFrame in timeseries_readings.
    Returns {rows_inserted, points_created}.
    """
    site_id_str = str(site_id)
    point_columns = [c for c in WEATHER_POINTS if c in df.columns]
    if not point_columns:
        return {"rows_inserted": 0, "points_created": 0}

    with get_conn() as conn:
        with conn.cursor() as cur:
            point_ids = {}
            for ext_id in point_columns:
                cur.execute(
                    """
                    INSERT INTO points (site_id, external_id) VALUES (%s, %s)
                    ON CONFLICT (site_id, external_id) DO UPDATE SET external_id = EXCLUDED.external_id
                    RETURNING id
                    """,
                    (site_id, ext_id),
                )
                point_ids[ext_id] = cur.fetchone()["id"]

            rows = []
            for _, r in df.iterrows():
                ts = r["ts"].to_pydatetime()
                for col in point_columns:
                    val = r.get(col)
                    if pd.notna(val):
                        try:
                            v = float(val)
                        except TypeError:
                            continue
                        except ValueError:
                            continue
                        rows.append((ts, site_id_str, point_ids[col], v, None))

            if rows:
                execute_values(
                    cur,
                    """
                    INSERT INTO timeseries_readings (ts, site_id, point_id, value, job_id)
                    VALUES %s
                    """,
                    rows,
                    page_size=2000,
                )
            conn.commit()

    return {"rows_inserted": len(rows), "points_created": len(point_ids)}


def run_open_meteo_fetch(
    site_id: uuid.UUID,
    lat: float,
    lon: float,
    days_back: int = 3,
    timezone: str = "America/Chicago",
) -> dict:
    """Fetch last N days of weather, store in DB."""
    end_d = date.today()
    start_d = end_d - timedelta(days=days_back)
    df = fetch_open_meteo(lat, lon, start_d, end_d, timezone=timezone)
    return store_weather_for_site(site_id, df)
