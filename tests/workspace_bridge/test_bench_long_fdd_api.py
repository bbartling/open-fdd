"""API tests for Bench long FDD evaluate endpoint."""

from __future__ import annotations

import sys
from pathlib import Path

import pyarrow as pa
import pytest

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def test_bench_long_fdd_evaluate_synthetic_table(monkeypatch: pytest.MonkeyPatch):
    from openfdd_bridge.bench_long_fdd_eval import BenchLongFddEvaluateBody, evaluate_long_fdd

    model = {
        "sites": [{"id": "demo"}],
        "equipment": [
            {"id": "bacnet-5007", "site_id": "demo"},
            {"id": "niagara-bench9065", "site_id": "demo"},
        ],
        "points": [
            {
                "id": "5007-analog-input-1192",
                "site_id": "demo",
                "equipment_id": "bacnet-5007",
                "external_id": "duct-t",
                "fdd_input": "duct-t",
                "brick_type": "Discharge_Air_Temperature_Sensor",
                "metadata": {"source": "bacnet_direct", "cross_source_semantic": "duct-t"},
            }
        ],
    }
    table = pa.table(
        {
            "timestamp": [f"2026-01-01T00:{i:02d}:00Z" for i in range(15)],
            "duct-t": [75.0] * 15,
            "site_id": ["demo"] * 15,
        }
    )

    def _fake_load(site_id, *, source="bacnet", columns=None):
        return table, "feather"

    monkeypatch.setattr("openfdd_bridge.data_loader.load_arrow_table_for_run", _fake_load)

    body = BenchLongFddEvaluateBody(
        site_id="demo",
        source="bacnet_direct",
        semantic_key="duct-t",
        backend="pyarrow",
        threshold=80.0,
        confirmation_rows=10,
        confirmation_minutes=10.0,
    )
    out = evaluate_long_fdd(body, model)
    assert out["ok"] is True
    metrics = out["metrics"]
    assert metrics["raw_true_count"] == 15
    assert metrics["execution_evidence"]["computation_path"] == "pyarrow_compute"
