from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from open_fdd.desktop.services.ingest_service import IngestService
from open_fdd.desktop.services.model_service import ModelService
from open_fdd.desktop.storage.feather_store import FeatherStore
from open_fdd.desktop.storage.model_store import ModelStore


def test_csv_ingest_creates_feather_refs(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    csv_path = tmp_path / "sample.csv"
    pd.DataFrame(
        {
            "timestamp": ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"],
            "sa_temp": [55.0, 56.0],
            "oa_temp": [20.0, 21.0],
        }
    ).to_csv(csv_path, index=False)

    model_store = ModelStore(path=tmp_path / "model.json")
    model_service = ModelService(store=model_store)
    site = model_service.create_site("HQ")
    ingest = IngestService(model_service=model_service, feather_store=FeatherStore(root=tmp_path / "feather"))
    out = ingest.ingest_csv(csv_path=csv_path, site_id=site["id"], source="csv")
    assert out["rows"] == 2
    model = model_service.load()
    assert any(p.get("external_id") == "sa_temp" for p in model["points"])
    sa_point = next(p for p in model["points"] if p.get("external_id") == "sa_temp")
    assert sa_point.get("metadata", {}).get("external_ref", "") == out["storage_path"]


def test_ingest_service_ml_baseline_returns_metrics(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    pytest.importorskip("sklearn")
    csv_path = tmp_path / "sample_ml.csv"
    ts = pd.date_range("2026-01-01", periods=240, freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "oat": [35.0 + (i % 24) * 0.4 for i in range(len(ts))],
            "rat": [70.0 + (i % 12) * 0.15 for i in range(len(ts))],
        }
    )
    df["sat"] = 46.0 + 0.35 * df["oat"] + 0.22 * df["rat"]
    df.to_csv(csv_path, index=False)

    model_store = ModelStore(path=tmp_path / "model.json")
    model_service = ModelService(store=model_store)
    site = model_service.create_site("HQ ML")
    ingest = IngestService(model_service=model_service, feather_store=FeatherStore(root=tmp_path / "feather"))
    ingest.ingest_csv(csv_path=csv_path, site_id=site["id"], source="csv")
    out = ingest.train_ml_baseline(
        site_id=site["id"],
        source="csv",
        target_col="sat",
        feature_cols=["oat", "rat"],
    )
    assert out["rows_train"] > 0
    assert out["rows_test"] > 0
    assert out["rows_scored"] > 0
    assert isinstance(out["r2"], float)
    assert 0.8 <= out["r2"] <= 1.0
    assert out["output_source"].startswith("ml_sat")

