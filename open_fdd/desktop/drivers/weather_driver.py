from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd

from open_fdd.desktop.storage.feather_store import FeatherStore


@dataclass
class WeatherFetchResult:
    rows: int
    source: str = "open_meteo"


def run_weather_fetch(*, store: FeatherStore, site_id: str, days_back: int = 1) -> WeatherFetchResult:
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
    return WeatherFetchResult(rows=int(len(frame.index)))

