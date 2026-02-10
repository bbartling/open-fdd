"""
Open-Meteo driver: fetch historical weather, write to timeseries_readings.

Configurable interval (e.g. once per day). Used for FDD rules that need OAT.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import uuid

import pandas as pd
import requests
from psycopg2.extras import execute_values

from open_fdd.platform.database import get_conn

WEATHER_POINTS = ["temp_f", "rh_pct", "dewpoint_f", "wind_mph", "gust_mph"]
OPEN_METEO_FIELDS = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "wind_speed_10m",
    "wind_gusts_10m",
]
COLUMN_MAP = {
    "temperature_2m": "temp_f",
    "relative_humidity_2m": "rh_pct",
    "dew_point_2m": "dewpoint_f",
    "wind_speed_10m": "wind_mph",
    "wind_gusts_10m": "gust_mph",
}


def fetch_open_meteo(
    lat: float,
    lon: float,
    start_date: date,
    end_date: date,
    timezone: str = "America/Chicago",
    base_url: str = "https://archive-api.open-meteo.com/v1/era5",
) -> pd.DataFrame:
    """Fetch hourly weather from Open-Meteo archive."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "hourly": ",".join(OPEN_METEO_FIELDS),
        "timezone": timezone,
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
    }
    resp = requests.get(base_url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        raise RuntimeError("No hourly.time in Open-Meteo response.")

    df = pd.DataFrame({"ts": pd.to_datetime(times)})
    for field in OPEN_METEO_FIELDS:
        df[COLUMN_MAP[field]] = hourly.get(field, [None] * len(df))

    tz = ZoneInfo(timezone)
    if df["ts"].dt.tz is None:
        df["ts"] = df["ts"].dt.tz_localize(tz)
    else:
        df["ts"] = df["ts"].dt.tz_convert(tz)

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
                        except (TypeError, ValueError):
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
