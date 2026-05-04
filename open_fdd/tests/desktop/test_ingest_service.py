from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest
import warnings

from open_fdd.desktop.services.ingest_service import IngestService
from open_fdd.desktop.services.model_service import ModelService
from open_fdd.desktop.storage.feather_store import FeatherStore
from open_fdd.desktop.storage.model_store import ModelStore

_FIXTURE_CSV_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "csv"


def test_csv_ingest_parse_error_does_not_touch_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("pyarrow")
    model_store = ModelStore(path=tmp_path / "model.json")
    model_service = ModelService(store=model_store)
    site = model_service.create_site("Bad CSV")
    before = len(model_service.load().get("points", []))
    ingest = IngestService(model_service=model_service, feather_store=FeatherStore(root=tmp_path / "feather"))

    def fake_ingest_csv(**kwargs: object) -> dict:
        return {
            "rows": 0,
            "dropped_rows": 0,
            "storage_path": "",
            "feather_path": "",
            "metrics": ["would_not_upsert"],
            "parse_error": "connector parse failed (test double)",
        }

    monkeypatch.setattr(ingest.connector, "ingest_csv", fake_ingest_csv)
    out = ingest.ingest_csv(csv_path=tmp_path / "ignored.csv", site_id=site["id"], source="csv")
    assert out.get("parse_error")
    after = len(model_service.load().get("points", []))
    assert after == before


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


def test_csv_ingest_appends_batches_to_same_equipment(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    csv_old = tmp_path / "old.csv"
    csv_new = tmp_path / "new.csv"
    pd.DataFrame(
        {
            "timestamp": ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"],
            "sat": [55.0, 56.0],
            "mat": [57.0, 57.5],
        }
    ).to_csv(csv_old, index=False)
    pd.DataFrame(
        {
            "timestamp": ["2026-01-01T02:00:00Z", "2026-01-01T03:00:00Z"],
            "sat": [57.0, 58.0],
            "mat": [58.0, 58.5],
        }
    ).to_csv(csv_new, index=False)

    model_store = ModelStore(path=tmp_path / "model.json")
    model_service = ModelService(store=model_store)
    site = model_service.create_site("AHU Site")
    eq = model_service.create_equipment(site_id=site["id"], name="AHU-1", equipment_type="Air_Handling_Unit")
    ingest = IngestService(model_service=model_service, feather_store=FeatherStore(root=tmp_path / "feather"))

    first = ingest.ingest_csv(csv_path=csv_old, site_id=site["id"], source="csv", equipment_id=eq["id"])
    second = ingest.ingest_csv(csv_path=csv_new, site_id=site["id"], source="csv", equipment_id=eq["id"])

    assert first["rows"] == 2
    assert second["rows"] == 2

    frame = ingest.load_source_frame(site_id=site["id"], source="csv")
    assert len(frame.index) == 4

    model = model_service.load()
    assert len(model["equipment"]) == 1
    assert len(model["points"]) == 2
    assert all(p.get("equipment_id") == eq["id"] for p in model["points"])


def test_rtu07_style_split_tsv_files_append_one_site_one_equipment(tmp_path: Path) -> None:
    """Two sequential CSV ingests for the same site + equipment append Feather shards (not new equipment)."""
    pytest.importorskip("pyarrow")
    p1 = _FIXTURE_CSV_DIR / "rtu07_part1.tsv"
    p2 = _FIXTURE_CSV_DIR / "rtu07_part2.tsv"
    assert p1.is_file() and p2.is_file()

    model_store = ModelStore(path=tmp_path / "model.json")
    model_service = ModelService(store=model_store)
    site = model_service.create_site("RTU07 lab")
    eq = model_service.create_equipment(
        site_id=site["id"],
        name="RTU07",
        equipment_type="Air_Handling_Unit",
    )
    ingest = IngestService(model_service=model_service, feather_store=FeatherStore(root=tmp_path / "feather"))

    first = ingest.ingest_csv(csv_path=p1, site_id=site["id"], source="csv", equipment_id=eq["id"])
    second = ingest.ingest_csv(csv_path=p2, site_id=site["id"], source="csv", equipment_id=eq["id"])
    assert first["rows"] >= 1 and second["rows"] >= 1

    frame = ingest.load_source_frame(site_id=site["id"], source="csv")
    assert len(frame.index) == first["rows"] + second["rows"]
    assert str(frame["timestamp"].min()).startswith("2026-02-02")
    assert str(frame["timestamp"].max()).startswith("2026-03-20")

    model = model_service.load()
    assert len(model["equipment"]) == 1
    assert len(model["points"]) == 3
    assert all(str(p.get("equipment_id")) == str(eq["id"]) for p in model["points"])


@pytest.mark.skipif(
    not (os.environ.get("OFDD_LIVE_AHU7_CSV_PART1") and os.environ.get("OFDD_LIVE_AHU7_CSV_PART2")),
    reason="Set OFDD_LIVE_AHU7_CSV_PART1 and OFDD_LIVE_AHU7_CSV_PART2 to full AHU7 export paths",
)
def test_live_two_part_operator_csv_ingest_from_env(tmp_path: Path) -> None:
    """Optional: run against your real split exports (same schema, same site)."""
    pytest.importorskip("pyarrow")
    p1 = Path(os.environ["OFDD_LIVE_AHU7_CSV_PART1"]).expanduser()
    p2 = Path(os.environ["OFDD_LIVE_AHU7_CSV_PART2"]).expanduser()
    model_store = ModelStore(path=tmp_path / "model.json")
    model_service = ModelService(store=model_store)
    site = model_service.create_site("AHU7 live")
    eq = model_service.create_equipment(site_id=site["id"], name="AHU7", equipment_type="Air_Handling_Unit")
    ingest = IngestService(model_service=model_service, feather_store=FeatherStore(root=tmp_path / "feather"))
    a = ingest.ingest_csv(csv_path=p1, site_id=site["id"], source="csv", equipment_id=eq["id"])
    b = ingest.ingest_csv(csv_path=p2, site_id=site["id"], source="csv", equipment_id=eq["id"])
    assert a.get("parse_error") is None and b.get("parse_error") is None
    frame = ingest.load_source_frame(site_id=site["id"], source="csv")
    assert len(frame.index) == int(a["rows"]) + int(b["rows"])


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


def test_ingest_service_time_bounds_and_window_filter(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    csv_path = tmp_path / "sample_window.csv"
    pd.DataFrame(
        {
            "timestamp": [
                "2026-01-01T00:00:00Z",
                "2026-01-01T01:00:00Z",
                "2026-01-01T02:00:00Z",
                "2026-01-01T03:00:00Z",
            ],
            "sat": [54.0, 55.0, 56.0, 57.0],
        }
    ).to_csv(csv_path, index=False)

    model_store = ModelStore(path=tmp_path / "model.json")
    model_service = ModelService(store=model_store)
    site = model_service.create_site("HQ Window")
    ingest = IngestService(model_service=model_service, feather_store=FeatherStore(root=tmp_path / "feather"))
    ingest.ingest_csv(csv_path=csv_path, site_id=site["id"], source="csv")

    bounds = ingest.source_time_bounds(site_id=site["id"], source="csv")
    assert bounds["rows"] == 4
    assert str(bounds["start"]).startswith("2026-01-01T00:00:00")
    assert str(bounds["end"]).startswith("2026-01-01T03:00:00")

    window = ingest.load_source_frame_window(
        site_id=site["id"],
        source="csv",
        start_ts="2026-01-01T01:00:00Z",
        end_ts="2026-01-01T02:00:00Z",
    )
    assert len(window.index) == 2
    assert [float(v) for v in window["sat"].tolist()] == [55.0, 56.0]


def test_load_merged_sources_frame_window_empty_sources_returns_tuple(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    model_store = ModelStore(path=tmp_path / "model.json")
    model_service = ModelService(store=model_store)
    site = model_service.create_site("HQ Empty merge")
    ingest = IngestService(model_service=model_service, feather_store=FeatherStore(root=tmp_path / "feather"))
    merged, used = ingest.load_merged_sources_frame_window(site_id=site["id"], sources=[])
    assert merged.empty
    assert used == []


def test_load_merged_sources_frame_window_outer_join(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    model_store = ModelStore(path=tmp_path / "model.json")
    model_service = ModelService(store=model_store)
    site = model_service.create_site("HQ Merge")
    ingest = IngestService(model_service=model_service, feather_store=FeatherStore(root=tmp_path / "feather"))

    csv_path = tmp_path / "a.csv"
    pd.DataFrame(
        {
            "timestamp": ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"],
            "sat": [54.0, 55.0],
        }
    ).to_csv(csv_path, index=False)
    ingest.ingest_csv(csv_path=csv_path, site_id=site["id"], source="csv")

    wx_path = tmp_path / "wx.csv"
    pd.DataFrame(
        {
            "timestamp": ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"],
            "oat": [20.0, 21.0],
        }
    ).to_csv(wx_path, index=False)
    ingest.ingest_csv(csv_path=wx_path, site_id=site["id"], source="weather")

    merged, used = ingest.load_merged_sources_frame_window(
        site_id=site["id"],
        sources=["csv", "weather"],
    )
    assert used == ["csv", "weather"]
    assert "sat_csv" in merged.columns
    assert "oat_weather" in merged.columns
    assert len(merged) == 2


def test_ingest_service_time_bounds_handles_unparseable_timestamps(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    csv_path = tmp_path / "sample_bad_ts.csv"
    pd.DataFrame(
        {
            "timestamp": ["not-a-date", "still-not-a-date"],
            "sat": [55.0, 56.0],
        }
    ).to_csv(csv_path, index=False)

    model_store = ModelStore(path=tmp_path / "model.json")
    model_service = ModelService(store=model_store)
    site = model_service.create_site("HQ Bad TS")
    ingest = IngestService(model_service=model_service, feather_store=FeatherStore(root=tmp_path / "feather"))
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Could not infer format")
        ingest.ingest_csv(csv_path=csv_path, site_id=site["id"], source="csv")

    bounds = ingest.source_time_bounds(site_id=site["id"], source="csv")
    assert bounds["rows"] == 0
    assert bounds["start"] is None
    assert bounds["end"] is None


def test_ingest_service_bacnet_ingest_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("pyarrow")
    from open_fdd.platform.drivers.bacnet_driver import BacnetScrapeResult

    model_store = ModelStore(path=tmp_path / "model.json")
    model_service = ModelService(store=model_store)
    site = model_service.create_site("HQ BACnet")
    model_service.create_point(
        site_id=site["id"],
        equipment_id=None,
        external_id="sat",
        brick_type="Supply_Air_Temperature_Sensor",
        metadata={},
    )
    with model_service.transaction() as model:
        p = model["points"][0]
        p["bacnet_device_id"] = "device,123456"
        p["object_identifier"] = "analog-input,1"
        p["polling"] = True

    def _fake_scrape(*, store, model, site_id, server_url, api_key=""):
        return BacnetScrapeResult(
            rows=1,
            source="bacnet",
            metrics=["sat"],
            storage_ref="feather://fake",
            point_metadata={"sat": {"brick_type": "Supply_Air_Temperature_Sensor", "fdd_input": "sat", "unit": "degF"}},
            success=True,
            devices_polled=1,
            points_polled=1,
        )

    monkeypatch.setattr(
        "open_fdd.desktop.services.ingest_service.run_bacnet_scrape",
        _fake_scrape,
    )
    ingest = IngestService(model_service=model_service, feather_store=FeatherStore(root=tmp_path / "feather"))
    out = ingest.ingest_bacnet(
        site_id=site["id"],
        server_url="http://192.168.204.18:8080",
        api_key="token",
    )
    assert out["success"] is True
    assert out["source"] == "bacnet"
    assert out["devices_polled"] == 1


def test_csv_ingest_rejects_unknown_equipment_id(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    csv_path = tmp_path / "sample.csv"
    pd.DataFrame({"timestamp": ["2026-01-01T00:00:00Z"], "sat": [55.0]}).to_csv(csv_path, index=False)
    model_store = ModelStore(path=tmp_path / "model.json")
    model_service = ModelService(store=model_store)
    site = model_service.create_site("HQ")
    model_service.create_equipment(site_id=site["id"], name="AHU-1", equipment_type="Air_Handling_Unit")
    ingest = IngestService(model_service=model_service, feather_store=FeatherStore(root=tmp_path / "feather"))
    with pytest.raises(ValueError, match="not valid"):
        ingest.ingest_csv(csv_path=csv_path, site_id=site["id"], source="csv", equipment_id="definitely-missing")


def test_csv_ingest_rejects_equipment_id_from_other_site(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    csv_path = tmp_path / "sample.csv"
    pd.DataFrame({"timestamp": ["2026-01-01T00:00:00Z"], "sat": [55.0]}).to_csv(csv_path, index=False)
    model_store = ModelStore(path=tmp_path / "model.json")
    model_service = ModelService(store=model_store)
    site_a = model_service.create_site("Site A")
    site_b = model_service.create_site("Site B")
    eq_b = model_service.create_equipment(site_id=site_b["id"], name="Only B", equipment_type="Air_Handling_Unit")
    ingest = IngestService(model_service=model_service, feather_store=FeatherStore(root=tmp_path / "feather"))
    with pytest.raises(ValueError, match="not valid"):
        ingest.ingest_csv(csv_path=csv_path, site_id=site_a["id"], source="csv", equipment_id=eq_b["id"])


def test_csv_ingest_same_metric_columns_create_separate_points_per_equipment(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    csv_a = tmp_path / "a.csv"
    csv_b = tmp_path / "b.csv"
    pd.DataFrame({"timestamp": ["2026-01-01T00:00:00Z"], "sat": [55.0]}).to_csv(csv_a, index=False)
    pd.DataFrame({"timestamp": ["2026-01-01T00:00:00Z"], "sat": [60.0]}).to_csv(csv_b, index=False)

    model_store = ModelStore(path=tmp_path / "model.json")
    model_service = ModelService(store=model_store)
    site = model_service.create_site("Multi")
    eq1 = model_service.create_equipment(site_id=site["id"], name="AHU-1", equipment_type="Air_Handling_Unit")
    eq2 = model_service.create_equipment(site_id=site["id"], name="AHU-2", equipment_type="Air_Handling_Unit")
    ingest = IngestService(model_service=model_service, feather_store=FeatherStore(root=tmp_path / "feather"))

    ingest.ingest_csv(csv_path=csv_a, site_id=site["id"], source="csv", equipment_id=eq1["id"])
    ingest.ingest_csv(csv_path=csv_b, site_id=site["id"], source="csv", equipment_id=eq2["id"])

    model = model_service.load()
    sat_points = [p for p in model["points"] if p.get("external_id") == "sat"]
    assert len(sat_points) == 2
    assert {p.get("equipment_id") for p in sat_points} == {eq1["id"], eq2["id"]}

