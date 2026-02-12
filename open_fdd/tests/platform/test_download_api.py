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
    """When site exists with data, expect 200 and CSV body."""
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
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment" in r.headers["content-disposition"]
    body = r.text
    assert "timestamp" in body
    assert "SA-T" in body
    assert "RA-T" in body


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
