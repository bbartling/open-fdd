"""Unit tests for CRUD API (sites, points, equipment)."""

from datetime import datetime, timezone
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app

client = TestClient(app)


def _mock_conn(fetchone=None, fetchall=None):
    """Build a mock DB connection. fetchone/fetchall can be single value or list for side_effect."""
    cursor = MagicMock()
    cursor.execute.return_value = None
    cursor.rowcount = 1
    cursor.fetchone.return_value = fetchone  # None for 404 cases, dict for success
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


@contextmanager
def _patch_db(conn):
    """Patch get_conn in all API modules that use it."""
    with (
        patch("open_fdd.platform.api.sites.get_conn", side_effect=lambda: conn),
        patch("open_fdd.platform.api.points.get_conn", side_effect=lambda: conn),
        patch("open_fdd.platform.api.equipment.get_conn", side_effect=lambda: conn),
    ):
        yield


def _patch_ttl():
    return (
        patch("open_fdd.platform.api.sites.sync_ttl_to_file")
        and patch("open_fdd.platform.api.points.sync_ttl_to_file")
        and patch("open_fdd.platform.api.equipment.sync_ttl_to_file")
    )


# --- Sites ---


def test_sites_list_empty():
    conn = _mock_conn(fetchall=[])
    with _patch_db(conn):
        r = client.get("/sites")
    assert r.status_code == 200
    assert r.json() == []


def test_sites_list_returns_sites():
    site_id = uuid4()
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "id": site_id,
            "name": "Default",
            "description": None,
            "metadata": None,
            "created_at": now,
        }
    ]
    conn = _mock_conn(fetchall=rows)
    with _patch_db(conn):
        r = client.get("/sites")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["name"] == "Default"
    assert data[0]["id"] == str(site_id)


def test_sites_create():
    site_id = uuid4()
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": site_id,
        "name": "TestSite",
        "description": "A site",
        "metadata": {},
        "created_at": now,
    }
    conn = _mock_conn(fetchone=row)
    with _patch_db(conn), patch("open_fdd.platform.api.sites.sync_ttl_to_file"):
        r = client.post("/sites", json={"name": "TestSite", "description": "A site"})
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "TestSite"
    assert data["id"] == str(site_id)


def test_sites_get():
    site_id = uuid4()
    row = {
        "id": site_id,
        "name": "Default",
        "description": None,
        "metadata": None,
        "created_at": "2024-01-01T00:00:00",
    }
    conn = _mock_conn(fetchone=row)
    with _patch_db(conn):
        r = client.get(f"/sites/{site_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Default"


def test_sites_get_404():
    conn = _mock_conn(fetchone=None)
    with _patch_db(conn):
        r = client.get(f"/sites/{uuid4()}")
    assert r.status_code == 404


def test_sites_patch():
    site_id = uuid4()
    row = {
        "id": site_id,
        "name": "Updated",
        "description": "New desc",
        "metadata": {},
        "created_at": "2024-01-01T00:00:00",
    }
    conn = _mock_conn(fetchone=row)
    with _patch_db(conn), patch("open_fdd.platform.api.sites.sync_ttl_to_file"):
        r = client.patch(f"/sites/{site_id}", json={"description": "New desc"})
    assert r.status_code == 200
    assert r.json()["description"] == "New desc"


def test_sites_delete():
    sid = uuid4()
    conn = _mock_conn(fetchone={"id": sid, "name": "TestSite"})
    with _patch_db(conn), patch("open_fdd.platform.api.sites.sync_ttl_to_file"):
        r = client.delete(f"/sites/{sid}")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"


def test_sites_delete_404():
    conn = _mock_conn(fetchone=None)
    with _patch_db(conn):
        r = client.delete(f"/sites/{uuid4()}")
    assert r.status_code == 404


# --- Equipment ---


def test_equipment_list_empty():
    conn = _mock_conn(fetchall=[])
    with _patch_db(conn):
        r = client.get("/equipment")
    assert r.status_code == 200
    assert r.json() == []


def test_equipment_create():
    site_id = uuid4()
    eq_id = uuid4()
    row = {
        "id": eq_id,
        "site_id": site_id,
        "name": "AHU-1",
        "description": None,
        "equipment_type": "Air_Handling_Unit",
        "created_at": "2024-01-01T00:00:00",
    }
    conn = _mock_conn(fetchone=row)
    with _patch_db(conn), patch("open_fdd.platform.api.equipment.sync_ttl_to_file"):
        r = client.post(
            "/equipment",
            json={
                "site_id": str(site_id),
                "name": "AHU-1",
                "equipment_type": "Air_Handling_Unit",
            },
        )
    assert r.status_code == 200
    assert r.json()["name"] == "AHU-1"


def test_equipment_get_404():
    conn = _mock_conn(fetchone=None)
    with _patch_db(conn):
        r = client.get(f"/equipment/{uuid4()}")
    assert r.status_code == 404


def test_equipment_delete():
    conn = _mock_conn(fetchone={"id": uuid4()})
    with _patch_db(conn), patch("open_fdd.platform.api.equipment.sync_ttl_to_file"):
        r = client.delete(f"/equipment/{uuid4()}")
    assert r.status_code == 200


# --- Points ---


def test_points_list_empty():
    conn = _mock_conn(fetchall=[])
    with _patch_db(conn):
        r = client.get("/points")
    assert r.status_code == 200
    assert r.json() == []


def test_points_create():
    site_id = uuid4()
    pt_id = uuid4()
    row = {
        "id": pt_id,
        "site_id": site_id,
        "external_id": "SA-T",
        "brick_type": "Supply_Air_Temperature_Sensor",
        "fdd_input": "sat",
        "unit": "degF",
        "description": None,
        "equipment_id": None,
        "created_at": "2024-01-01T00:00:00",
    }
    conn = _mock_conn(fetchone=row)
    with _patch_db(conn), patch("open_fdd.platform.api.points.sync_ttl_to_file"):
        r = client.post(
            "/points",
            json={
                "site_id": str(site_id),
                "external_id": "SA-T",
                "brick_type": "Supply_Air_Temperature_Sensor",
                "fdd_input": "sat",
                "unit": "degF",
            },
        )
    assert r.status_code == 200
    assert r.json()["external_id"] == "SA-T"


def test_points_get_404():
    conn = _mock_conn(fetchone=None)
    with _patch_db(conn):
        r = client.get(f"/points/{uuid4()}")
    assert r.status_code == 404


def test_points_patch():
    pt_id = uuid4()
    site_id = uuid4()
    row = {
        "id": pt_id,
        "site_id": site_id,
        "external_id": "SA-T",
        "brick_type": "Zone_Temperature_Sensor",
        "fdd_input": "zt",
        "unit": None,
        "description": None,
        "equipment_id": None,
        "created_at": "2024-01-01T00:00:00",
    }
    conn = _mock_conn(fetchone=row)
    with _patch_db(conn), patch("open_fdd.platform.api.points.sync_ttl_to_file"):
        r = client.patch(
            f"/points/{pt_id}", json={"brick_type": "Zone_Temperature_Sensor"}
        )
    assert r.status_code == 200
    assert r.json()["brick_type"] == "Zone_Temperature_Sensor"


def test_points_delete():
    conn = _mock_conn(fetchone={"id": uuid4()})
    with _patch_db(conn), patch("open_fdd.platform.api.points.sync_ttl_to_file"):
        r = client.delete(f"/points/{uuid4()}")
    assert r.status_code == 200
