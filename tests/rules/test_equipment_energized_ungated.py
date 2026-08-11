"""equipment_energized must ungate when no fan/pump/compressor proof exists."""

from __future__ import annotations

import pandas as pd

from open_fdd.rules.operational_gate import resolve_operational_mask


def test_sv_range_without_proof_is_ungated():
    idx = pd.date_range("2024-01-01", periods=3, freq="5min", tz="UTC")
    df = pd.DataFrame({"outside-air-temp": [70, 71, 72]}, index=idx)
    active, meta = resolve_operational_mask(df, "SV-RANGE", poll_seconds=300)
    assert bool(active.all())
    assert meta["gate_kind"] == "equipment_energized"
    assert str(meta.get("gate_source", "")).startswith("ungated")
