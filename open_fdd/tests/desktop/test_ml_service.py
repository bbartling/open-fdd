from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("pyarrow")
pytest.importorskip("sklearn")

from open_fdd.desktop.services.ml_service import MLService
from open_fdd.desktop.storage.connectors import FeatherConnector
from open_fdd.desktop.storage.feather_store import FeatherStore


def test_ml_service_train_baseline_writes_predictions(tmp_path: Path) -> None:
    store = FeatherStore(root=tmp_path / "feather")
    connector = FeatherConnector(store=store)
    ts = pd.date_range("2026-01-01", periods=200, freq="1h", tz="UTC")
    frame = pd.DataFrame(
        {
            "timestamp": ts,
            "oat": [30.0 + (i % 24) * 0.5 for i in range(len(ts))],
            "rat": [70.0 + (i % 8) * 0.2 for i in range(len(ts))],
        }
    )
    frame["sat"] = 45.0 + 0.4 * frame["oat"] + 0.2 * frame["rat"]
    frame["sat_fault_flag"] = ((frame.index >= 150) & (frame.index < 165)).astype(int)
    connector.write_frame(source="csv", site_id="site-a", frame=frame)

    svc = MLService(connector=connector)
    out = svc.train_baseline(
        site_id="site-a",
        source="csv",
        target_col="sat",
        feature_cols=["oat", "rat"],
        lag_cols=["oat"],
        rule_flag_col="sat_fault_flag",
        residual_quantile=0.9,
    )
    assert out.rows_train > 0
    assert out.rows_test > 0
    assert out.rows_scored > 0
    assert out.output_source.startswith("ml_sat")
    scored = connector.read_frame(source=out.output_source, site_id="site-a")
    assert "ml_prediction" in scored.columns
    assert "ml_residual_fault" in scored.columns


def test_ml_service_train_baseline_errors_on_missing_target(tmp_path: Path) -> None:
    store = FeatherStore(root=tmp_path / "feather")
    connector = FeatherConnector(store=store)
    ts = pd.date_range("2026-01-01", periods=120, freq="1h", tz="UTC")
    frame = pd.DataFrame({"timestamp": ts, "oat": [40.0] * len(ts), "rat": [72.0] * len(ts)})
    connector.write_frame(source="csv", site_id="site-b", frame=frame)

    svc = MLService(connector=connector)
    with pytest.raises(ValueError, match="Target column not found"):
        svc.train_baseline(site_id="site-b", source="csv", target_col="sat")


def test_ml_service_overlap_not_inflated_with_duplicate_timestamps(tmp_path: Path) -> None:
    store = FeatherStore(root=tmp_path / "feather")
    connector = FeatherConnector(store=store)
    base_ts = pd.Timestamp("2026-01-01T00:00:00Z")
    ts = [base_ts + pd.Timedelta(hours=i // 2) for i in range(120)]  # duplicate each timestamp twice
    frame = pd.DataFrame(
        {
            "timestamp": ts,
            "oat": [30.0 + (i % 24) * 0.25 for i in range(len(ts))],
            "rat": [70.0 + (i % 6) * 0.5 for i in range(len(ts))],
        }
    )
    frame["sat"] = 44.0 + 0.4 * frame["oat"] + 0.2 * frame["rat"]  # perfect linear relation
    frame["sat_fault_flag"] = 1
    connector.write_frame(source="csv", site_id="site-c", frame=frame)

    svc = MLService(connector=connector)
    out = svc.train_baseline(
        site_id="site-c",
        source="csv",
        target_col="sat",
        feature_cols=["oat", "rat"],
        rule_flag_col="sat_fault_flag",
        residual_quantile=0.5,
    )
    # Residuals are exactly zero in this setup, so all rows are flagged (>= threshold 0).
    assert out.overlap_with_rule_flag == out.rows_scored
