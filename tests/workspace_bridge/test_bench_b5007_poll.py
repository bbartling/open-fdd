"""Tests for bench device 5007 poll setup."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_model_points_for_5007(monkeypatch):
    from openfdd_bridge.bench_b5007_poll import _model_points_for_device
    from openfdd_bridge.model_service import ModelService
    from openfdd_bridge.ttl_service import TtlService

    model_path = REPO / "workspace" / "data" / "bench_dual_source_model.json"
    if not model_path.is_file():
        pytest.skip("bench model missing")
    svc = ModelService()
    svc.import_json(json.loads(model_path.read_text(encoding="utf-8")), replace=True)
    TtlService().sync()

    rows = _model_points_for_device()
    pids = {r["point_id"] for r in rows}
    assert "5007-analog-input-1173" in pids
    assert "5007-analog-input-1168" in pids
    assert len(rows) == 4


@patch("openfdd_bridge.bench_b5007_poll.ensure_commission_agent", return_value={"ok": True, "already_running": True})
@patch("openfdd_bridge.bench_b5007_poll.commission_poll_once", return_value=(200, {"ok": True, "samples": 4}))
def test_enable_bench_5007_poll_configures_csv(mock_poll, _mock_comm):
    from openfdd_bridge.bench_b5007_poll import enable_bench_5007_poll
    from openfdd_bridge.model_service import ModelService
    from openfdd_bridge.ttl_service import TtlService

    model_path = REPO / "workspace" / "data" / "bench_dual_source_model.json"
    if not model_path.is_file():
        pytest.skip("bench model missing")
    svc = ModelService()
    svc.import_json(json.loads(model_path.read_text(encoding="utf-8")), replace=True)
    TtlService().sync()

    from openfdd_bridge.paths import workspace_dir

    out = enable_bench_5007_poll(poll_interval_s=60, start_commission=False)
    assert out.get("ok") is True
    assert out.get("point_count") == 4

    points_csv = workspace_dir() / "bacnet" / "commissioning" / "points.csv"
    assert points_csv.is_file()
    text = points_csv.read_text(encoding="utf-8")
    assert "5007-analog-input-1173" in text
    assert "poll_interval_s" in text or ",60," in text.replace('"', "")


def test_append_live_tick(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "seed_bench_poll_samples",
        REPO / "scripts" / "seed_bench_poll_samples.py",
    )
    seed = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(seed)

    poll = tmp_path / "samples.csv"
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path / "workspace" / "data"))
    (tmp_path / "workspace" / "data").mkdir(parents=True)

    with patch("openfdd_bridge.bacnet_poll_ingest.ingest_poll_samples_to_feather", return_value={"ok": True, "rows_long": 4}):
        out = seed.append_live_tick(poll_path=poll)
    assert out.get("ok")
    assert poll.is_file()
    lines = poll.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 5  # header + 4 points
