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

from openfdd_stack.platform.api.main import app

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
        patch("openfdd_stack.platform.api.sites.get_conn", side_effect=lambda: conn),
        patch("openfdd_stack.platform.api.points.get_conn", side_effect=lambda: conn),
        patch("openfdd_stack.platform.api.equipment.get_conn", side_effect=lambda: conn),
    ):
        yield


def _patch_ttl():
    return (
        patch("openfdd_stack.platform.api.sites.sync_ttl_to_file")
        and patch("openfdd_stack.platform.api.points.sync_ttl_to_file")
        and patch("openfdd_stack.platform.api.equipment.sync_ttl_to_file")
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
    with _patch_db(conn), patch("openfdd_stack.platform.api.sites.sync_ttl_to_file"):
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
    with _patch_db(conn), patch("openfdd_stack.platform.api.sites.sync_ttl_to_file"):
        r = client.patch(f"/sites/{site_id}", json={"description": "New desc"})
    assert r.status_code == 200
    assert r.json()["description"] == "New desc"


def test_sites_delete():
    sid = uuid4()
    conn = _mock_conn(fetchone={"id": sid, "name": "TestSite"})
    with _patch_db(conn), patch("openfdd_stack.platform.api.sites.sync_ttl_to_file"):
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
    conn = _mock_conn(
        fetchone={"id": str(uuid4())}
    )  # duplicate check finds existing site
    with _patch_db(conn):
        r = client.post("/sites", json={"name": "ExistingSite", "description": "x"})
    assert r.status_code == 409
    msg = (r.json().get("error") or {}).get("message", "") or r.json().get("detail", "")
    assert "name" in msg.lower() or "already" in msg.lower()


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
    conn = _mock_conn(
        fetchone={"id": str(uuid4())}
    )  # duplicate check finds existing equipment
    with _patch_db(conn):
        r = client.post(
            "/equipment",
            json={"site_id": str(site_id), "name": "AHU-1", "equipment_type": "AHU"},
        )
    assert r.status_code == 409
    msg = (r.json().get("error") or {}).get("message", "") or r.json().get("detail", "")
    assert "equipment" in msg.lower() or "name" in msg.lower()


def test_equipment_create():
    site_id = uuid4()
    eq_id = uuid4()
    row = {
        "id": eq_id,
        "site_id": site_id,
        "name": "AHU-1",
        "description": None,
        "equipment_type": "Air_Handling_Unit",
        "metadata": {"engineering": {"controls": {"control_vendor": "Acme"}}},
        "created_at": "2024-01-01T00:00:00",
    }
    # First fetchone: duplicate check (no existing equipment); second: INSERT RETURNING
    conn = _mock_conn(fetchone=row)
    conn.cursor.return_value.__enter__.return_value.fetchone.side_effect = [None, row]
    with _patch_db(conn), patch("openfdd_stack.platform.api.equipment.sync_ttl_to_file"):
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
    assert r.json()["metadata"]["engineering"]["controls"]["control_vendor"] == "Acme"


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


def test_equipment_patch_metadata_deep_merges_nested_keys():
    eq_id = uuid4()
    site_id = uuid4()
    updated_row = {
        "id": str(eq_id),
        "site_id": str(site_id),
        "name": "AHU-1",
        "description": None,
        "equipment_type": "Air_Handling_Unit",
        "metadata": {
            "engineering": {
                "controls": {"control_vendor": "Acme", "panel_name": "P1"},
                "mechanical": {"design_cfm": "5000"},
            }
        },
        "feeds_equipment_id": None,
        "fed_by_equipment_id": None,
        "created_at": "2024-01-01T00:00:00",
    }
    cursor = MagicMock()
    cursor.execute.return_value = None
    # 1) SELECT metadata for merge, 2) UPDATE ... RETURNING for PATCH response
    cursor.fetchone.side_effect = [
        {"metadata": {"engineering": {"controls": {"control_vendor": "Acme"}}}},
        updated_row,
    ]
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    conn.commit = MagicMock()

    with _patch_db(conn), patch("openfdd_stack.platform.api.equipment.sync_ttl_to_file"):
        r = client.patch(
            f"/equipment/{eq_id}",
            json={"metadata": {"engineering": {"controls": {"panel_name": "P1"}}}},
        )
    assert r.status_code == 200
    # Merge preserves existing nested keys and applies incoming updates.
    assert r.json()["metadata"]["engineering"]["controls"]["control_vendor"] == "Acme"
    assert r.json()["metadata"]["engineering"]["controls"]["panel_name"] == "P1"


def test_equipment_delete():
    conn = _mock_conn(fetchone={"id": uuid4()})
    with _patch_db(conn), patch("openfdd_stack.platform.api.equipment.sync_ttl_to_file"):
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
    """POST /points with same (site_id, external_id) returns 409 when INSERT hits unique constraint (e.g. race)."""
    if psycopg2 is None:
        pytest.skip("psycopg2 required for IntegrityError test")
    site_id = uuid4()
    cursor = MagicMock()
    cursor.execute.side_effect = [
        None,
        psycopg2.IntegrityError("duplicate key value violates unique constraint"),
    ]
    cursor.fetchone.return_value = None  # SELECT finds no existing
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    with _patch_db(conn):
        r = client.post(
            "/points",
            json={"site_id": str(site_id), "external_id": "SA-T", "unit": "degF"},
        )
    assert r.status_code == 409
    msg = (r.json().get("error") or {}).get("message", "") or r.json().get("detail", "")
    assert "external_id" in msg.lower() or "already" in msg.lower()


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
    with _patch_db(conn), patch("openfdd_stack.platform.api.points.sync_ttl_to_file"):
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
    with _patch_db(conn), patch("openfdd_stack.platform.api.points.sync_ttl_to_file"):
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


def test_points_create_with_modbus_config():
    site_id = uuid4()
    pt_id = uuid4()
    mc = {
        "host": "10.0.0.5",
        "port": 502,
        "unit_id": 1,
        "timeout": 5.0,
        "address": 4000,
        "count": 2,
        "function": "holding",
        "decode": "float32",
    }
    row = {
        "id": pt_id,
        "site_id": site_id,
        "external_id": "meter_kW",
        "brick_type": "Power_Sensor",
        "fdd_input": "meter_kw",
        "unit": "kW",
        "description": "Main meter",
        "equipment_id": None,
        "bacnet_device_id": None,
        "object_identifier": None,
        "object_name": None,
        "polling": True,
        "modbus_config": mc,
        "created_at": "2024-01-01T00:00:00",
    }
    conn = _mock_conn(fetchone=row)
    with _patch_db(conn), patch("openfdd_stack.platform.api.points.sync_ttl_to_file"):
        r = client.post(
            "/points",
            json={
                "site_id": str(site_id),
                "external_id": "meter_kW",
                "brick_type": "Power_Sensor",
                "fdd_input": "meter_kw",
                "unit": "kW",
                "description": "Main meter",
                "modbus_config": mc,
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert data["external_id"] == "meter_kW"
    assert data["modbus_config"]["host"] == "10.0.0.5"
    assert data["modbus_config"]["address"] == 4000


def test_points_create_invalid_modbus_config_422():
    site_id = uuid4()
    conn = _mock_conn(fetchone=None)
    with _patch_db(conn):
        r = client.post(
            "/points",
            json={
                "site_id": str(site_id),
                "external_id": "bad_modbus",
                "modbus_config": {"host": "", "address": 0},
            },
        )
    assert r.status_code == 422


def test_points_create_modbus_float32_count_one_422():
    """32-bit decode requires count >= 2 at CRUD boundary (same rule as normalize_modbus_config)."""
    site_id = uuid4()
    conn = _mock_conn(fetchone=None)
    with _patch_db(conn):
        r = client.post(
            "/points",
            json={
                "site_id": str(site_id),
                "external_id": "bad_modbus_count",
                "modbus_config": {
                    "host": "10.0.0.1",
                    "address": 0,
                    "count": 1,
                    "function": "holding",
                    "decode": "float32",
                },
            },
        )
    assert r.status_code == 422


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
    with _patch_db(conn), patch("openfdd_stack.platform.api.points.sync_ttl_to_file"):
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
    with _patch_db(conn), patch("openfdd_stack.platform.api.points.sync_ttl_to_file"):
        r = client.patch(
            f"/points/{pt_id}",
            json={"bacnet_device_id": "999", "object_identifier": "analog-value,2"},
        )
    assert r.status_code == 200
    assert r.json()["bacnet_device_id"] == "999"
    assert r.json()["object_identifier"] == "analog-value,2"


def test_points_delete():
    conn = _mock_conn(fetchone={"id": uuid4()})
    with _patch_db(conn), patch("openfdd_stack.platform.api.points.sync_ttl_to_file"):
        r = client.delete(f"/points/{uuid4()}")
    assert r.status_code == 200
