"""Unit tests for CRUD API (sites, points, equipment)."""

from datetime import datetime, timezone
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

try:
    import psycopg2
except ImportError:
    psycopg2 = None

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
    # First fetchone: duplicate check (no existing site); second: INSERT RETURNING
    conn = _mock_conn(fetchone=row)
    conn.cursor.return_value.__enter__.return_value.fetchone.side_effect = [None, row]
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


def test_sites_create_409_duplicate_name():
    """POST /sites with an existing name returns 409 so serialized graph has no duplicate site names."""
    conn = _mock_conn(fetchone={"id": str(uuid4())})  # duplicate check finds existing site
    with _patch_db(conn):
        r = client.post("/sites", json={"name": "ExistingSite", "description": "x"})
    assert r.status_code == 409
    assert "name" in r.json().get("detail", "").lower() or "already" in r.json().get("detail", "").lower()


def test_sites_patch_409_duplicate_name():
    """PATCH /sites to a name that another site has returns 409."""
    site_id = uuid4()
    conn = _mock_conn(fetchone={"id": str(uuid4())})  # other site with that name exists
    with _patch_db(conn):
        r = client.patch(f"/sites/{site_id}", json={"name": "OtherSiteName"})
    assert r.status_code == 409


# --- Equipment ---


def test_equipment_list_empty():
    conn = _mock_conn(fetchall=[])
    with _patch_db(conn):
        r = client.get("/equipment")
    assert r.status_code == 200
    assert r.json() == []


def test_equipment_create_409_duplicate_name_same_site():
    """POST /equipment with same (site_id, name) returns 409 so serialized graph has no duplicate equipment per site."""
    site_id = uuid4()
    conn = _mock_conn(fetchone={"id": str(uuid4())})  # duplicate check finds existing equipment
    with _patch_db(conn):
        r = client.post(
            "/equipment",
            json={"site_id": str(site_id), "name": "AHU-1", "equipment_type": "AHU"},
        )
    assert r.status_code == 409
    assert "equipment" in r.json().get("detail", "").lower() or "name" in r.json().get("detail", "").lower()


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
    # First fetchone: duplicate check (no existing equipment); second: INSERT RETURNING
    conn = _mock_conn(fetchone=row)
    conn.cursor.return_value.__enter__.return_value.fetchone.side_effect = [None, row]
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


def test_equipment_patch_409_duplicate_name_same_site():
    """PATCH /equipment to a name that another equipment on the same site has returns 409."""
    eq_id = uuid4()
    site_id = uuid4()
    # First fetchone: existing equipment (for site_id); second: other eq with same name exists
    cursor = MagicMock()
    cursor.execute.return_value = None
    cursor.fetchone.side_effect = [
        {"id": str(eq_id), "site_id": str(site_id)},
        {"id": str(uuid4())},
    ]
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    conn.commit = MagicMock()
    with _patch_db(conn):
        r = client.patch(f"/equipment/{eq_id}", json={"name": "OtherAHU"})
    assert r.status_code == 409


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


def test_points_create_409_duplicate_external_id_same_site():
    """POST /points with same (site_id, external_id) returns 409 so serialized graph has no duplicate points per site."""
    if psycopg2 is None:
        pytest.skip("psycopg2 required for IntegrityError test")
    site_id = uuid4()
    cursor = MagicMock()
    cursor.execute.side_effect = psycopg2.IntegrityError("duplicate key value violates unique constraint")
    cursor.fetchone.return_value = None
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    conn.commit = MagicMock()
    with _patch_db(conn):
        r = client.post(
            "/points",
            json={"site_id": str(site_id), "external_id": "SA-T", "unit": "degF"},
        )
    assert r.status_code == 409
    assert "external_id" in r.json().get("detail", "").lower() or "already" in r.json().get("detail", "").lower()


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
        "bacnet_device_id": None,
        "object_identifier": None,
        "object_name": None,
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


def test_points_create_with_bacnet_fields():
    site_id = uuid4()
    pt_id = uuid4()
    row = {
        "id": pt_id,
        "site_id": site_id,
        "external_id": "DAP-P",
        "brick_type": "Sensor",
        "fdd_input": None,
        "unit": None,
        "description": None,
        "equipment_id": None,
        "bacnet_device_id": "3456789",
        "object_identifier": "analog-input,1",
        "object_name": "DAP-P",
        "created_at": "2024-01-01T00:00:00",
    }
    conn = _mock_conn(fetchone=row)
    with _patch_db(conn), patch("open_fdd.platform.api.points.sync_ttl_to_file"):
        r = client.post(
            "/points",
            json={
                "site_id": str(site_id),
                "external_id": "DAP-P",
                "bacnet_device_id": "3456789",
                "object_identifier": "analog-input,1",
                "object_name": "DAP-P",
                "brick_type": "Sensor",
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert data["external_id"] == "DAP-P"
    assert data["bacnet_device_id"] == "3456789"
    assert data["object_identifier"] == "analog-input,1"
    assert data["object_name"] == "DAP-P"


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
        "bacnet_device_id": None,
        "object_identifier": None,
        "object_name": None,
        "created_at": "2024-01-01T00:00:00",
    }
    conn = _mock_conn(fetchone=row)
    with _patch_db(conn), patch("open_fdd.platform.api.points.sync_ttl_to_file"):
        r = client.patch(
            f"/points/{pt_id}", json={"brick_type": "Zone_Temperature_Sensor"}
        )
    assert r.status_code == 200
    assert r.json()["brick_type"] == "Zone_Temperature_Sensor"


def test_points_list_includes_bacnet_fields():
    site_id = uuid4()
    pt_id = uuid4()
    rows = [
        {
            "id": pt_id,
            "site_id": site_id,
            "external_id": "ai-1",
            "brick_type": "Sensor",
            "fdd_input": None,
            "unit": None,
            "description": None,
            "equipment_id": None,
            "bacnet_device_id": "123",
            "object_identifier": "analog-input,1",
            "object_name": "ai-1",
            "created_at": "2024-01-01T00:00:00",
        }
    ]
    conn = _mock_conn(fetchall=rows)
    with _patch_db(conn):
        r = client.get("/points")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["bacnet_device_id"] == "123"
    assert data[0]["object_identifier"] == "analog-input,1"
    assert data[0]["object_name"] == "ai-1"


def test_points_patch_bacnet_fields():
    pt_id = uuid4()
    site_id = uuid4()
    row = {
        "id": pt_id,
        "site_id": site_id,
        "external_id": "pt",
        "brick_type": "Point",
        "fdd_input": None,
        "unit": None,
        "description": None,
        "equipment_id": None,
        "bacnet_device_id": "999",
        "object_identifier": "analog-value,2",
        "object_name": "pt",
        "created_at": "2024-01-01T00:00:00",
    }
    conn = _mock_conn(fetchone=row)
    with _patch_db(conn), patch("open_fdd.platform.api.points.sync_ttl_to_file"):
        r = client.patch(
            f"/points/{pt_id}",
            json={"bacnet_device_id": "999", "object_identifier": "analog-value,2"},
        )
    assert r.status_code == 200
    assert r.json()["bacnet_device_id"] == "999"
    assert r.json()["object_identifier"] == "analog-value,2"


def test_points_delete():
    conn = _mock_conn(fetchone={"id": uuid4()})
    with _patch_db(conn), patch("open_fdd.platform.api.points.sync_ttl_to_file"):
        r = client.delete(f"/points/{uuid4()}")
    assert r.status_code == 200
