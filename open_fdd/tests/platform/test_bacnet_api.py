"""Tests for BACnet API (proxy routes and import-discovery)."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app

client = TestClient(app)


def test_import_discovery_422_when_no_point_discoveries():
    """POST /bacnet/import-discovery returns 422 when point_discoveries is missing or empty."""
    r = client.post("/bacnet/import-discovery", json={})
    assert r.status_code == 422
    r2 = client.post(
        "/bacnet/import-discovery",
        json={"site_id": "default", "devices": [{"device_instance": 123}]},
    )
    assert r2.status_code == 422


def test_import_discovery_accepts_normalized_point_discoveries():
    """POST /bacnet/import-discovery creates points when given normalized point_discoveries."""
    site_uuid = uuid4()
    eq_uuid = uuid4()

    def mock_cursor():
        cur = MagicMock()
        cur.execute.return_value = None
        # First call: SELECT equipment -> None (create new). Second: INSERT equipment RETURNING id
        cur.fetchone.side_effect = [None, {"id": eq_uuid}]
        return cur

    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor())
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    conn.commit = MagicMock()

    with (
        patch("open_fdd.platform.api.bacnet.get_conn", side_effect=lambda: conn),
        patch(
            "open_fdd.platform.api.bacnet.resolve_site_uuid",
            return_value=site_uuid,
        ),
        patch("open_fdd.platform.api.bacnet.sync_ttl_to_file"),
    ):
        r = client.post(
            "/bacnet/import-discovery",
            json={
                "site_id": str(site_uuid),
                "point_discoveries": [
                    {
                        "device_instance": 3456789,
                        "objects": [
                            {
                                "object_identifier": "analog-input,1",
                                "object_name": "DAP-P",
                            }
                        ],
                    }
                ],
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "imported"
    assert data["points_created"] == 1
    assert data["site_id"] == str(site_uuid)


def test_import_discovery_parses_raw_point_discovery_result():
    """Import accepts raw point_discovery_result shape (like diy-bacnet-server response)."""
    site_uuid = uuid4()
    eq_uuid = uuid4()

    def mock_cursor():
        cur = MagicMock()
        cur.execute.return_value = None
        cur.fetchone.side_effect = [None, {"id": eq_uuid}]
        return cur

    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor())
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    conn.commit = MagicMock()

    with (
        patch("open_fdd.platform.api.bacnet.get_conn", side_effect=lambda: conn),
        patch(
            "open_fdd.platform.api.bacnet.resolve_site_uuid",
            return_value=site_uuid,
        ),
        patch("open_fdd.platform.api.bacnet.sync_ttl_to_file"),
    ):
        r = client.post(
            "/bacnet/import-discovery",
            json={
                "point_discovery_result": {
                    "result": {
                        "device_instance": 100,
                        "objects": [
                            {
                                "object_identifier": "binary-value,1",
                                "object_name": "BV-1",
                            }
                        ],
                    }
                },
            },
        )
    assert r.status_code == 200
    assert r.json()["points_created"] == 1
