"""Standalone WattLab CLI: pandas default; datafusion never silently falls back."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

WATT = Path(__file__).resolve().parents[2] / "tools" / "wattlab_export"


@pytest.fixture(scope="module")
def agent_api():
    sys.path.insert(0, str(WATT))
    try:
        from app import agent_api as mod  # type: ignore
    except ImportError:
        pytest.skip("tools/wattlab_export not importable")
    return mod


def test_run_rules_pandas_engine_no_central_import(agent_api):
    idx = pd.date_range("2026-01-05", periods=12, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {
            "sat": 55.0,
            "sat_sp": 55.0,
            "fan_status": 1.0,
            "htg_valve_pct": 0.0,
        },
        index=idx,
    )
    ds = agent_api.AgentDataset(
        building_id="SYNTH",
        frames={"AHU_1": df},
        weather=None,
    )
    run = agent_api.run_rules(
        ds, engine="pandas", rule_ids=["FC7"], require_operational_gates=False
    )
    assert run.meta.get("requested_engine") == "pandas"
    assert run.meta.get("actual_engine") == "pandas"


def test_datafusion_does_not_silent_fallback(agent_api):
    idx = pd.date_range("2026-01-05", periods=4, freq="5min", tz="UTC")
    df = pd.DataFrame({"sat": 55.0}, index=idx)
    ds = agent_api.AgentDataset(building_id="SYNTH", frames={"AHU_1": df}, weather=None)
    with pytest.raises((RuntimeError, ImportError)):
        agent_api.run_rules(ds, engine="datafusion")
