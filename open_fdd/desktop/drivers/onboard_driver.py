from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from open_fdd.desktop.storage.feather_store import FeatherStore


@dataclass
class OnboardScrapeResult:
    rows: int


def run_onboard_scrape(*, store: FeatherStore, site_id: str) -> OnboardScrapeResult:
    now = datetime.now(timezone.utc)
    frame = pd.DataFrame(
        {
            "timestamp": [now],
            "diagnostic_source": ["onboard"],
            "value": [1.0],
        }
    )
    store.write_frame(source="onboard", site_id=site_id, frame=frame)
    return OnboardScrapeResult(rows=1)

