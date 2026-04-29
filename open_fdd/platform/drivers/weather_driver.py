from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from typing import Protocol
import urllib.parse
import urllib.request

import pandas as pd

logger = logging.getLogger(__name__)


class FrameStore(Protocol):
    def write_frame(self, *, source: str, site_id: str, frame: pd.DataFrame) -> str: ...


@dataclass
class WeatherFetchResult:
    rows: int
    source: str = "synthetic"


def run_weather_fetch(*, store: FrameStore, site_id: str, days_back: int = 1) -> WeatherFetchResult:
    # Optional live fetch via Open-Meteo when location is configured.
    lat = os.getenv("OFDD_OPEN_METEO_LATITUDE", "").strip()
    lon = os.getenv("OFDD_OPEN_METEO_LONGITUDE", "").strip()
    if lat and lon:
        live_frame: pd.DataFrame | None = None
        try:
            end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            start = end - timedelta(days=max(1, int(days_back)))
            base_url = os.getenv("OFDD_OPEN_METEO_BASE_URL", "https://archive-api.open-meteo.com/v1/archive").strip()
            parsed_base = urllib.parse.urlparse(base_url)
            if parsed_base.scheme not in {"http", "https"}:
                raise ValueError(f"Invalid Open-Meteo base URL scheme: {base_url}")
            params = {
                "latitude": float(lat),
                "longitude": float(lon),
                "start_date": start.date().isoformat(),
                "end_date": end.date().isoformat(),
                "hourly": "temperature_2m,relative_humidity_2m",
                "timezone": os.getenv("OFDD_OPEN_METEO_TIMEZONE", "UTC").strip() or "UTC",
            }
            url = f"{base_url}?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            hourly = body.get("hourly", {}) if isinstance(body, dict) else {}
            ts = hourly.get("time") or []
            temp = hourly.get("temperature_2m") or []
            rh = hourly.get("relative_humidity_2m") or []
            utc_offset_seconds = body.get("utc_offset_seconds") if isinstance(body, dict) else None
            if utc_offset_seconds is not None:
                parsed_ts = pd.to_datetime(ts, errors="coerce")
                offset = timezone(timedelta(seconds=int(utc_offset_seconds)))
                parsed_ts = parsed_ts.tz_localize(offset).tz_convert("UTC")
            else:
                parsed_ts = pd.to_datetime(ts, errors="coerce", utc=True)
            live_frame = pd.DataFrame(
                {
                    "timestamp": parsed_ts,
                    "outside_air_temp_c": pd.to_numeric(temp, errors="coerce"),
                    "outside_air_rh_pct": pd.to_numeric(rh, errors="coerce"),
                }
            )
            live_frame = live_frame[live_frame["timestamp"].notna()].copy()
        except Exception as exc:
            logger.exception("Open-Meteo live fetch or parse failed, falling back to synthetic weather: %s", exc)
            live_frame = None

        if live_frame is not None and len(live_frame.index) > 0:
            source = "weather"
            try:
                store.write_frame(source=source, site_id=site_id, frame=live_frame)
            except Exception:
                logger.exception("Failed to persist Open-Meteo weather frame for site_id=%s", site_id)
                raise
            return WeatherFetchResult(rows=len(live_frame.index), source=source)

    # Fallback synthetic weather profile.
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=max(1, int(days_back)))
    rng = pd.date_range(start=start, end=end, freq="1h", tz="UTC")
    frame = pd.DataFrame(
        {
            "timestamp": rng,
            "outside_air_temp_c": [12.0] * len(rng),
            "outside_air_rh_pct": [55.0] * len(rng),
        }
    )
    store.write_frame(source="weather", site_id=site_id, frame=frame)
    return WeatherFetchResult(rows=len(frame.index))
