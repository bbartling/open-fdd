from __future__ import annotations

import os
import sys
from pathlib import Path

import pyarrow as pa
import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from open_fdd.arrow_runtime.datafusion_backend import datafusion_available, lint_datafusion_sql_rule

GOOD_SQL = """SELECT
  *,
  "SAT" > 75.0 AS fault
FROM telemetry"""

SQL_RULE = {
    "name": "Zone temp SQL",
    "mode": "rule",
    "backend": "datafusion_sql",
    "sql": GOOD_SQL,
    "fault_column": "fault",
    "code": "# DataFusion SQL rule — see sql field",
    "enabled": False,
}


def test_rules_lab_lint_sql_endpoint_shape():
    lint = lint_datafusion_sql_rule(GOOD_SQL)
    assert lint["ok"] is True


def test_rules_lab_lint_rejects_insert():
    lint = lint_datafusion_sql_rule("INSERT INTO telemetry VALUES (1)")
    assert lint["ok"] is False


def test_compare_fault_mask_stats_null_aware():
    from openfdd_bridge.rules_lab import compare_fault_mask_stats

    left = pa.array([None, True, None, False], type=pa.bool_())
    right = pa.array([False, True, None, None], type=pa.bool_())
    matching, mismatching, _mismatch = compare_fault_mask_stats(left, right)
    assert matching == 2
    assert mismatching == 2


def test_sql_rule_lab_save_stores_backend(client: TestClient):
    r = client.post("/api/rules/lab/save", json=SQL_RULE)
    assert r.status_code == 200
    rule = r.json()["rule"]
    assert rule["backend"] == "datafusion_sql"
    assert rule["sql"].strip() == GOOD_SQL.strip()
    assert rule["fault_column"] == "fault"
    client.delete(f"/api/rules/saved/{rule['id']}")


def test_sql_rule_rename_preserves_sql_fields(client: TestClient):
    created = client.post("/api/rules/lab/save", json=SQL_RULE)
    assert created.status_code == 200
    rule_id = created.json()["rule"]["id"]
    original_sql = created.json()["rule"]["sql"]

    renamed = client.post(
        "/api/rules/lab/save",
        json={
            **SQL_RULE,
            "id": rule_id,
            "name": "Renamed SQL rule",
        },
    )
    assert renamed.status_code == 200
    updated = renamed.json()["rule"]
    assert updated["name"] == "Renamed SQL rule"
    assert updated["backend"] == "datafusion_sql"
    assert updated["sql"] == original_sql
    assert updated["fault_column"] == "fault"

    listed = client.get("/api/rules/saved").json()["rules"]
    found = next(r for r in listed if r["id"] == rule_id)
    assert found["backend"] == "datafusion_sql"
    assert found["sql"] == original_sql

    client.delete(f"/api/rules/saved/{rule_id}")


def test_validate_preview_clean_error_without_traceback(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OFDD_DEBUG_TRACEBACKS", raising=False)
    bad = client.post(
        "/api/rules/lab/preview",
        json={
            "backend": "datafusion_sql",
            "sql": "SELECT * FROM telemetry",
            "fault_column": "fault",
            "limit": 50,
        },
    )
    assert bad.status_code == 200
    body = bad.json()
    assert body["ok"] is False
    assert "trace" not in str(body.get("details") or "").lower() or "Traceback" not in str(body.get("details") or "")


def test_lint_rejects_read_parquet():
    lint = lint_datafusion_sql_rule("SELECT *, true AS fault FROM read_parquet('/tmp/x.parquet')")
    assert lint["ok"] is False


def test_lint_rejects_other_table():
    lint = lint_datafusion_sql_rule("SELECT *, true AS fault FROM other_table")
    assert lint["ok"] is False


def test_lint_rejects_double_statement():
    lint = lint_datafusion_sql_rule("SELECT * FROM telemetry; SELECT * FROM telemetry")
    assert lint["ok"] is False


def test_lint_rejects_missing_fault_projection():
    lint = lint_datafusion_sql_rule("SELECT * FROM telemetry WHERE zone_temp > 75")
    assert lint["ok"] is False


def test_lint_rejects_wrong_fault_column_name():
    lint = lint_datafusion_sql_rule("SELECT *, zone_temp > 75 AS not_fault FROM telemetry")
    assert lint["ok"] is False


@pytest.mark.skipif(not datafusion_available(), reason="datafusion optional extra not installed")
def test_sql_rule_participates_in_batch(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path / "data"))
    created = client.post(
        "/api/rules/lab/save",
        json={
            **SQL_RULE,
            "name": "Batch SQL test",
            "enabled": True,
            "config": {"min_true_rows": 1},
        },
    )
    assert created.status_code == 200
    rule_id = created.json()["rule"]["id"]
    batch = client.post("/api/rules/batch", json={"limit": 100})
    assert batch.status_code == 200
    runs = batch.json().get("runs") or []
    sql_run = next((r for r in runs if r.get("rule_id") == rule_id), None)
    assert sql_run is not None
    assert sql_run.get("backend") == "datafusion_sql"
    assert sql_run.get("status") in {"ok", "error"}
    if sql_run.get("status") == "error":
        err = str(sql_run.get("error") or "").lower()
        assert "datafusion" in err or "schema" in err or "row" in err
    client.delete(f"/api/rules/saved/{rule_id}")
