"""Unit tests for data-model API (export, import, TTL, SPARQL) — validates API/sql/data-model sync."""

from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app

client = TestClient(app)


def _mock_conn_with_cursor(fetchall_result):
    cursor = MagicMock()
    cursor.fetchall.return_value = fetchall_result
    cursor.execute.return_value = None
    cursor.rowcount = 1
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    return conn


def test_data_model_export_empty():
    with patch("open_fdd.platform.api.data_model.get_conn", side_effect=lambda: _mock_conn_with_cursor([])):
        r = client.get("/data-model/export")
    assert r.status_code == 200
    assert r.json() == []


def test_data_model_export_returns_point_refs():
    site_id = uuid4()
    point_id = uuid4()
    rows = [
        {
            "id": point_id,
            "site_id": site_id,
            "site_name": "Default",
            "external_id": "SA-T",
            "equipment_id": None,
            "equipment_name": None,
            "brick_type": "Supply_Air_Temperature_Sensor",
            "fdd_input": "sat",
            "unit": "degF",
        }
    ]
    with patch("open_fdd.platform.api.data_model.get_conn", side_effect=lambda: _mock_conn_with_cursor(rows)):
        r = client.get("/data-model/export")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["external_id"] == "SA-T"
    assert data[0]["point_id"] == str(point_id)
    assert data[0]["brick_type"] == "Supply_Air_Temperature_Sensor"
    assert data[0]["fdd_input"] == "sat"


def test_data_model_ttl_generated_from_db():
    site_id = uuid4()
    sites = [{"id": site_id, "name": "Default"}]
    equipment = []
    points = [
        {
            "id": uuid4(),
            "site_id": site_id,
            "external_id": "ZoneTemp",
            "brick_type": "Zone_Temperature_Sensor",
            "fdd_input": "zt",
            "unit": None,
            "equipment_id": None,
        }
    ]
    cursor = MagicMock()
    cursor.fetchall.side_effect = [sites, equipment, points]
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    with patch("open_fdd.platform.data_model_ttl.get_conn", return_value=conn):
        r = client.get("/data-model/ttl")
    assert r.status_code == 200
    assert "text/turtle" in r.headers.get("content-type", "")
    assert "brick:Site" in r.text
    assert "Default" in r.text
    assert "ZoneTemp" in r.text
    assert "Zone_Temperature_Sensor" in r.text


def test_data_model_sparql_returns_bindings():
    site_id = uuid4()
    sites = [{"id": site_id, "name": "Default"}]
    equipment = []
    points = [
        {
            "id": uuid4(),
            "site_id": site_id,
            "external_id": "SA-T",
            "brick_type": "Point",
            "fdd_input": None,
            "unit": None,
            "equipment_id": None,
        }
    ]
    cursor = MagicMock()
    cursor.fetchall.side_effect = [sites, equipment, points]
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    query = "PREFIX brick: <https://brickschema.org/schema/Brick#> SELECT ?s WHERE { ?s a brick:Site } LIMIT 1"
    with patch("open_fdd.platform.data_model_ttl.get_conn", return_value=conn):
        r = client.post("/data-model/sparql", json={"query": query})
    assert r.status_code == 200
    data = r.json()
    assert "bindings" in data
    assert isinstance(data["bindings"], list)
    if data["bindings"]:
        assert "s" in data["bindings"][0]


def test_data_model_import_updates_points():
    cursor = MagicMock()
    cursor.rowcount = 1
    cursor.execute.return_value = None
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    body = {
        "points": [
            {"point_id": str(uuid4()), "brick_type": "Supply_Air_Temperature_Sensor", "fdd_input": "sat"}
        ]
    }
    with patch("open_fdd.platform.api.data_model.get_conn", side_effect=lambda: conn):
        r = client.put("/data-model/import", json=body)
    assert r.status_code == 200
    data = r.json()
    assert "updated" in data
    assert "total" in data
    assert data["total"] == 1
