"""Analytics API tests (GET /analytics/fault-summary, /analytics/fault-timeseries)."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from openfdd_stack.platform.api.main import app

client = TestClient(app)


def test_fault_summary_returns_shape():
    with patch("openfdd_stack.platform.api.analytics.get_conn") as mock_conn:
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = [
            {"fault_id": "fc1", "count": 10, "flag_sum": 10},
            {"fault_id": "fc2", "count": 2, "flag_sum": 2},
        ]
        cur.fetchone.return_value = {"n": 2}
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=None)
        mock_conn.return_value = conn

        r = client.get(
            "/analytics/fault-summary?start_date=2025-01-01&end_date=2025-01-07"
        )
    assert r.status_code == 200
    data = r.json()
    assert (
        "period" in data
        and "by_fault_id" in data
        and "total_faults" in data
        and "active_in_period" in data
    )
    assert data["total_faults"] == 12
    assert data["active_in_period"] == 2
    assert len(data["by_fault_id"]) == 2


def test_fault_summary_404_unknown_site():
    with patch("openfdd_stack.platform.api.analytics.resolve_site_uuid", return_value=None):
        r = client.get(
            "/analytics/fault-summary?site_id=nosuch&start_date=2025-01-01&end_date=2025-01-07"
        )
    assert r.status_code == 404


def test_fault_timeseries_returns_shape():
    with patch("openfdd_stack.platform.api.analytics.get_conn") as mock_conn:
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = [
            {"time": datetime(2025, 1, 1, 12, 0), "metric": "fc1", "value": 1.0},
            {"time": datetime(2025, 1, 1, 13, 0), "metric": "fc1", "value": 0.0},
        ]
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=None)
        mock_conn.return_value = conn

        r = client.get(
            "/analytics/fault-timeseries?start_date=2025-01-01&end_date=2025-01-07&bucket=hour"
        )
    assert r.status_code == 200
    data = r.json()
    assert "period" in data and "bucket" in data and "series" in data
    assert data["bucket"] == "hour"
    assert len(data["series"]) == 2
    assert data["series"][0]["metric"] == "fc1" and data["series"][0]["value"] == 1.0


def test_fault_timeseries_invalid_bucket_rejected():
    with patch("openfdd_stack.platform.api.analytics.get_conn") as mock_conn:
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = []
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=None)
        mock_conn.return_value = conn

        r = client.get(
            "/analytics/fault-timeseries?start_date=2025-01-01&end_date=2025-01-07&bucket=invalid"
        )
    assert r.status_code == 422


def test_fault_timeseries_equipment_ids_adds_sql_filter():
    """Plots page passes equipment_ids so aggregates are not site-wide for a single device."""
    eq = "550e8400-e29b-41d4-a716-446655440000"
    with patch("openfdd_stack.platform.api.analytics.get_conn") as mock_conn:
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = []
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=None)
        mock_conn.return_value = conn

        r = client.get(
            f"/analytics/fault-timeseries?start_date=2025-01-01&end_date=2025-01-07&bucket=hour"
            f"&equipment_ids={eq}"
        )
    assert r.status_code == 200
    assert r.json()["equipment_ids"] == [eq]
    cur.execute.assert_called_once()
    sql, params = cur.execute.call_args[0]
    assert "fr.equipment_id IN" in sql
    assert eq in params


def test_system_host_empty_when_no_table():
    with patch("openfdd_stack.platform.api.analytics._table_exists", return_value=False):
        r = client.get("/analytics/system/host")
    assert r.status_code == 200
    assert r.json()["hosts"] == []


def test_system_containers_empty_when_no_table():
    with patch("openfdd_stack.platform.api.analytics._table_exists", return_value=False):
        r = client.get("/analytics/system/containers")
    assert r.status_code == 200
    assert r.json()["containers"] == []


def test_system_disk_empty_when_no_table():
    with patch("openfdd_stack.platform.api.analytics._table_exists", return_value=False):
        r = client.get("/analytics/system/disk")
    assert r.status_code == 200
    assert r.json()["disks"] == []


def test_container_logs_invalid_ref_rejected():
    r = client.get("/analytics/system/containers/bad!name/logs?follow=false")
    assert r.status_code == 400


def test_container_logs_snapshot_when_docker_mocked():
    fake_container = MagicMock()
    fake_container.logs.return_value = b"2025-01-01T00:00:00 line one\n"
    fake_client = MagicMock()
    fake_client.containers.get.return_value = fake_container
    with patch(
        "openfdd_stack.platform.api.analytics._docker_client", return_value=fake_client
    ):
        r = client.get("/analytics/system/containers/openfdd_api/logs?follow=false&tail=50")
    assert r.status_code == 200
    assert r.text == "2025-01-01T00:00:00 line one\n"
    fake_client.containers.get.assert_called_once_with("openfdd_api")
    fake_container.logs.assert_called_once_with(
        stream=False, tail=50, timestamps=True
    )


def test_container_logs_snapshot_404_when_not_found():
    DockerNotFound = type("NotFound", (Exception,), {})
    DockerNotFound.__module__ = "docker.errors"

    fake_client = MagicMock()
    fake_client.containers.get.side_effect = DockerNotFound("nope")
    with patch(
        "openfdd_stack.platform.api.analytics._docker_client", return_value=fake_client
    ):
        r = client.get("/analytics/system/containers/missing/logs?follow=false")
    assert r.status_code == 404


def test_container_logs_snapshot_503_when_no_docker():
    with patch("openfdd_stack.platform.api.analytics._docker_client", return_value=None):
        r = client.get("/analytics/system/containers/foo/logs?follow=false")
    assert r.status_code == 503
