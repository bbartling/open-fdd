from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.operational_analytics import (  # noqa: E402
    analytics_lookback_days,
    trim_frame_to_lookback,
)


def test_default_lookback_14_days(monkeypatch):
    monkeypatch.delenv("OFDD_ANALYTICS_LOOKBACK_DAYS", raising=False)
    assert analytics_lookback_days() == 14


def test_trim_frame_to_lookback():
    end = pd.Timestamp.now(tz="UTC")
    ts = pd.date_range(end=end, periods=30, freq="1D")
    df = pd.DataFrame({"timestamp": ts, "x": range(30)})
    trimmed = trim_frame_to_lookback(df, hours=24 * 14)
    assert len(trimmed) <= 15
