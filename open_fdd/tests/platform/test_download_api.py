"""Unit tests for download API."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app

client = TestClient(app)


def _mock_conn(fetchone=None, fetchall=None):
    """Build a mock DB connection."""
    cursor = MagicMock()
    cursor.execute.return_value = None
    cursor.rowcount = 1
    cursor.fetchone.return_value = fetchone
    if fetchall is not None:
        cursor.fetchall.return_value = (
            fetchall if isinstance(fetchall, list) else [fetchall]
        )
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    conn.commit = MagicMock()
    return conn


def test_download_csv_404_site_not_found():
    """When resolve_site_uuid returns None, expect 404."""
    with patch("open_fdd.platform.api.download.resolve_site_uuid", return_value=None):
        r = client.post(
            "/download/csv",
            json={
                "site_id": "unknown-site",
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
            },
        )
    assert r.status_code == 404
    assert "No site found" in r.json()["detail"]


def test_download_csv_404_no_data():
    """When site exists but no rows, expect 404."""
    site_id = uuid4()
    conn = _mock_conn(fetchall=[])
    with (
        patch("open_fdd.platform.api.download.resolve_site_uuid", return_value=site_id),
        patch("open_fdd.platform.api.download.get_conn", side_effect=lambda: conn),
    ):
        r = client.post(
            "/download/csv",
            json={
                "site_id": str(site_id),
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
            },
        )
    assert r.status_code == 404
    assert "No data" in r.json()["detail"]


def test_download_csv_200_wide():
    """When site exists with data, expect 200 and CSV body; wide = timestamp first (Excel-friendly)."""
    site_id = uuid4()
    rows = [
        {"ts": "2024-01-01 12:00:00", "external_id": "SA-T", "value": 72.5},
        {"ts": "2024-01-01 12:00:00", "external_id": "RA-T", "value": 70.0},
        {"ts": "2024-01-02 12:00:00", "external_id": "SA-T", "value": 73.0},
    ]
    conn = _mock_conn(fetchall=rows)
    with (
        patch("open_fdd.platform.api.download.resolve_site_uuid", return_value=site_id),
        patch("open_fdd.platform.api.download.get_conn", side_effect=lambda: conn),
    ):
        r = client.post(
            "/download/csv",
            json={
                "site_id": str(site_id),
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
                "format": "wide",
            },
        )
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    body = r.text
    assert "timestamp" in body
    assert "SA-T" in body
    assert "RA-T" in body
    # Bulk download default: timestamp column on left for Excel/Sheets users (like BAS trend export)
    first_line = body.strip().split("\n")[0]
    assert first_line.startswith("\ufeff") or "timestamp" in first_line
    assert first_line.split(",")[0].lstrip("\ufeff") == "timestamp"


def test_download_csv_200_long():
    """Long format returns ts, point_key, value columns."""
    site_id = uuid4()
    rows = [
        {"ts": "2024-01-01 12:00:00", "external_id": "SA-T", "value": 72.5},
    ]
    conn = _mock_conn(fetchall=rows)
    with (
        patch("open_fdd.platform.api.download.resolve_site_uuid", return_value=site_id),
        patch("open_fdd.platform.api.download.get_conn", side_effect=lambda: conn),
    ):
        r = client.post(
            "/download/csv",
            json={
                "site_id": str(site_id),
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
                "format": "long",
            },
        )
    assert r.status_code == 200
    assert "point_key" in r.text
    assert "SA-T" in r.text


def test_download_faults_404_site_not_found():
    """When site_id is provided and site does not exist, expect 404."""
    with patch("open_fdd.platform.api.download.resolve_site_uuid", return_value=None):
        r = client.get(
            "/download/faults?site_id=nosuch&start_date=2024-01-01&end_date=2024-01-31&format=csv"
        )
    assert r.status_code == 404
    assert "No site found" in r.json()["detail"]


def test_download_faults_200_csv():
    """Faults CSV: 200, timestamp first column, Excel-friendly (BOM, ISO timestamps)."""
    rows = [
        {
            "ts": "2024-01-15 10:00:00",
            "site_id": "default",
            "equipment_id": "ahu-1",
            "fault_id": "fault_flatline_flag",
            "flag_value": 1,
            "evidence": None,
        },
    ]
    conn = _mock_conn(fetchall=rows)
    with patch("open_fdd.platform.api.download.get_conn", side_effect=lambda: conn):
        r = client.get(
            "/download/faults?start_date=2024-01-01&end_date=2024-01-31&format=csv"
        )
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "openfdd_faults" in r.headers["content-disposition"]
    body = r.text
    assert body.startswith("\ufeff")  # UTF-8 BOM for Excel
    first_line = body.strip().split("\n")[0].lstrip("\ufeff")
    assert first_line.split(",")[0] == "timestamp"
    assert "fault_flatline_flag" in body
    assert "default" in body


def test_download_faults_200_json():
    """Faults JSON: 200, faults array and count for API/cloud integration."""
    rows = [
        {
            "ts": "2024-01-15 10:00:00",
            "site_id": "default",
            "equipment_id": "ahu-1",
            "fault_id": "fault_flatline_flag",
            "flag_value": 1,
            "evidence": None,
        },
    ]
    conn = _mock_conn(fetchall=rows)
    with patch("open_fdd.platform.api.download.get_conn", side_effect=lambda: conn):
        r = client.get(
            "/download/faults?start_date=2024-01-01&end_date=2024-01-31&format=json"
        )
    assert r.status_code == 200
    data = r.json()
    assert "faults" in data
    assert data["count"] == 1
    assert data["faults"][0]["fault_id"] == "fault_flatline_flag"
    assert "ts" in data["faults"][0]
