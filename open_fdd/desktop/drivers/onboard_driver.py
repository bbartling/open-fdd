from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

import pandas as pd

class FrameStore(Protocol):
    def write_frame(self, *, source: str, site_id: str, frame: pd.DataFrame) -> str: ...


@dataclass
class OnboardScrapeResult:
    rows: int
    source: str = "onboard"


def run_onboard_scrape(*, store: FrameStore, site_id: str) -> OnboardScrapeResult:
    # TODO: Replace with the real onboard scraper integration.
    now = datetime.now(timezone.utc)
    frame = pd.DataFrame(
        {
            "timestamp": [now],
            "diagnostic_source": ["onboard"],
            "value": [1.0],
        }
    )
    store.write_frame(source="onboard", site_id=site_id, frame=frame)
    return OnboardScrapeResult(rows=len(frame.index), source="onboard")

