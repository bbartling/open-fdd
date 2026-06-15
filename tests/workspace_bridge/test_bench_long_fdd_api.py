"""API tests for Bench long FDD evaluate endpoint."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pyarrow as pa
import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

_BENCH_MODEL = {
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


def test_bench_long_fdd_evaluate_synthetic_table(monkeypatch: pytest.MonkeyPatch):
    from openfdd_bridge.bench_long_fdd_eval import BenchLongFddEvaluateBody, evaluate_long_fdd

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
    out = evaluate_long_fdd(body, _BENCH_MODEL)
    assert out["ok"] is True
    metrics = out["metrics"]
    assert metrics["raw_true_count"] == 15
    assert metrics["execution_evidence"]["computation_path"] == "pyarrow_compute"


def test_bench_long_fdd_evaluate_missing_alignment():
    from openfdd_bridge.bench_long_fdd_eval import BenchLongFddEvaluateBody, evaluate_long_fdd

    body = BenchLongFddEvaluateBody(semantic_key="missing-semantic", source="bacnet_direct")
    out = evaluate_long_fdd(body, _BENCH_MODEL)
    assert out["ok"] is False
    assert "no model alignment" in out["error"]


def test_bench_long_fdd_evaluate_missing_historian(monkeypatch: pytest.MonkeyPatch):
    from openfdd_bridge.bench_long_fdd_eval import BenchLongFddEvaluateBody, evaluate_long_fdd

    def _empty_load(site_id, *, source="bacnet", columns=None):
        return pa.table({"timestamp": [], "duct-t": []}), "feather"

    monkeypatch.setattr("openfdd_bridge.data_loader.load_arrow_table_for_run", _empty_load)
    body = BenchLongFddEvaluateBody()
    out = evaluate_long_fdd(body, _BENCH_MODEL)
    assert out["ok"] is False
    assert "no historian data" in out["error"]


def test_bench_long_fdd_http_invalid_backend(client: TestClient):
    res = client.post(
        "/api/bench/long-fdd/evaluate",
        json={"backend": "python_list", "semantic_key": "duct-t"},
    )
    assert res.status_code == 422


def test_bench_long_fdd_http_invalid_source(client: TestClient):
    res = client.post(
        "/api/bench/long-fdd/evaluate",
        json={"source": "metasys_hack", "semantic_key": "duct-t"},
    )
    assert res.status_code == 422


def test_bench_long_fdd_http_clean_error_no_traceback(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OFDD_DEBUG_TRACEBACKS", raising=False)
    monkeypatch.setattr("openfdd_bridge.model_store.ModelStore.load", lambda self: _BENCH_MODEL)

    def _empty_load(site_id, *, source="bacnet", columns=None):
        return pa.table({"timestamp": [], "duct-t": []}), "feather"

    monkeypatch.setattr("openfdd_bridge.data_loader.load_arrow_table_for_run", _empty_load)
    res = client.post("/api/bench/long-fdd/evaluate", json={"semantic_key": "duct-t"})
    assert res.status_code == 200
    body = res.json()
    assert body.get("ok") is False
    assert "trace" not in json.dumps(body).lower()


def test_bench_long_fdd_http_success(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("openfdd_bridge.model_store.ModelStore.load", lambda self: _BENCH_MODEL)
    table = pa.table(
        {
            "timestamp": [f"2026-01-01T00:{i:02d}:00Z" for i in range(12)],
            "duct-t": [75.0] * 12,
            "site_id": ["demo"] * 12,
        }
    )

    def _fake_load(site_id, *, source="bacnet", columns=None):
        return table, "feather"

    monkeypatch.setattr("openfdd_bridge.data_loader.load_arrow_table_for_run", _fake_load)
    res = client.post(
        "/api/bench/long-fdd/evaluate",
        json={"backend": "pyarrow", "threshold": 80.0, "confirmation_rows": 10},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["metrics"]["execution_evidence"]["computation_path"] == "pyarrow_compute"
    text = json.dumps(body).lower()
    assert "password" not in text
    assert "bearer" not in text or "********" in text
