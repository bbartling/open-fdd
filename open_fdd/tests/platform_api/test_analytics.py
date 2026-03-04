"""Analytics API tests (GET /analytics/fault-summary, /analytics/fault-timeseries)."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app

client = TestClient(app)


def test_fault_summary_returns_shape():
    with patch("open_fdd.platform.api.analytics.get_conn") as mock_conn:
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = [
            {"fault_id": "fc1", "count": 10, "flag_sum": 10},
            {"fault_id": "fc2", "count": 2, "flag_sum": 2},
        ]
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=None)
        mock_conn.return_value = conn

        r = client.get("/analytics/fault-summary?start_date=2025-01-01&end_date=2025-01-07")
    assert r.status_code == 200
    data = r.json()
    assert "period" in data and "by_fault_id" in data and "total_faults" in data
    assert data["total_faults"] == 12
    assert len(data["by_fault_id"]) == 2


def test_fault_summary_404_unknown_site():
    with patch("open_fdd.platform.api.analytics.resolve_site_uuid", return_value=None):
        r = client.get(
            "/analytics/fault-summary?site_id=nosuch&start_date=2025-01-01&end_date=2025-01-07"
        )
    assert r.status_code == 404


def test_fault_timeseries_returns_shape():
    with patch("open_fdd.platform.api.analytics.get_conn") as mock_conn:
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


def test_fault_timeseries_invalid_bucket_defaults_to_hour():
    with patch("open_fdd.platform.api.analytics.get_conn") as mock_conn:
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
    assert r.status_code == 200
    assert r.json()["bucket"] == "hour"


def test_system_host_empty_when_no_table():
    with patch("open_fdd.platform.api.analytics._table_exists", return_value=False):
        r = client.get("/analytics/system/host")
    assert r.status_code == 200
    assert r.json()["hosts"] == []


def test_system_containers_empty_when_no_table():
    with patch("open_fdd.platform.api.analytics._table_exists", return_value=False):
        r = client.get("/analytics/system/containers")
    assert r.status_code == 200
    assert r.json()["containers"] == []


def test_system_disk_empty_when_no_table():
    with patch("open_fdd.platform.api.analytics._table_exists", return_value=False):
        r = client.get("/analytics/system/disk")
    assert r.status_code == 200
    assert r.json()["disks"] == []
