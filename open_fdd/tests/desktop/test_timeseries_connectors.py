from __future__ import annotations

from pathlib import Path

import pandas as pd

from open_fdd.desktop.services.ingest_service import IngestService
from open_fdd.desktop.services.model_service import ModelService
from open_fdd.desktop.storage.connectors import SqliteConnector
from open_fdd.desktop.storage.feather_store import FeatherStore
from open_fdd.desktop.storage.model_store import ModelStore


def test_sqlite_connector_roundtrip(tmp_path: Path) -> None:
    connector = SqliteConnector(db_path=str(tmp_path / "timeseries.db"))
    frame = pd.DataFrame(
        {
            "timestamp": ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"],
            "sa_temp": [55.0, 56.0],
            "oa_temp": [20.0, 21.0],
        }
    )
    connector.write_frame(source="csv", site_id="site-1", frame=frame)
    out = connector.read_frame(source="csv", site_id="site-1")
    assert not out.empty
    assert "timestamp" in out.columns
    assert "sa_temp" in out.columns


def test_sqlite_connector_replace_frame_atomic(tmp_path: Path) -> None:
    connector = SqliteConnector(db_path=str(tmp_path / "timeseries.db"))
    df1 = pd.DataFrame(
        {
            "timestamp": ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"],
            "sa_temp": [55.0, 56.0],
        }
    )
    connector.write_frame(source="csv", site_id="site-1", frame=df1)
    df2 = pd.DataFrame({"timestamp": ["2026-01-01T02:00:00Z"], "sa_temp": [57.0]})
    connector.replace_frame(source="csv", site_id="site-1", frame=df2)
    out = connector.read_frame(source="csv", site_id="site-1")
    assert len(out.index) == 1
    assert float(out["sa_temp"].iloc[0]) == 57.0


def test_ingest_service_uses_configured_connector(tmp_path: Path) -> None:
    csv_path = tmp_path / "sample.csv"
    pd.DataFrame(
        {
            "timestamp": ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"],
            "sat": [55.0, 56.0],
        }
    ).to_csv(csv_path, index=False)

    model_store = ModelStore(path=tmp_path / "model.json")
    model_service = ModelService(store=model_store)
    site = model_service.create_site("HQ")
    connector = SqliteConnector(db_path=str(tmp_path / "timeseries.db"))
    ingest = IngestService(
        model_service=model_service,
        feather_store=FeatherStore(root=tmp_path / "feather"),
        connector=connector,
    )
    ingest.ingest_csv(csv_path=csv_path, site_id=site["id"], source="csv")
    out = ingest.load_source_frame(source="csv", site_id=site["id"])
    assert not out.empty
    assert "sat" in out.columns

