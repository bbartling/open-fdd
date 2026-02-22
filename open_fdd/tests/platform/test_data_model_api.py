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
    with (
        patch(
            "open_fdd.platform.api.data_model.serialize_to_ttl",
            return_value="@prefix brick: <https://brickschema.org/schema/Brick#> .\n",
        ),
        patch(
            "open_fdd.platform.api.data_model.get_conn",
            side_effect=lambda: _mock_conn_with_cursor([]),
        ),
    ):
        r = client.get("/data-model/export")
    assert r.status_code == 200
    assert r.json() == []


def test_data_model_export_bacnet_only_returns_list():
    """GET /data-model/export?bacnet_only=true returns 200 and list of BACnet discovery rows."""
    minimal_bacnet_ttl = """
@prefix bacnet: <http://data.ashrae.org/bacnet/2020#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<bacnet://3456789> a bacnet:Device ;
    rdfs:label "AHU1" ;
    bacnet:device-instance 3456789 ;
    bacnet:contains <bacnet://3456789/analog-input,1> .
<bacnet://3456789/analog-input,1> bacnet:object-identifier "analog-input,1" ;
    bacnet:object-name "SA-T" .
"""
    with (
        patch(
            "open_fdd.platform.api.data_model.serialize_to_ttl",
            return_value=minimal_bacnet_ttl,
        ),
        patch(
            "open_fdd.platform.api.data_model.get_conn",
            side_effect=lambda: _mock_conn_with_cursor([]),
        ),
    ):
        r = client.get("/data-model/export?bacnet_only=true")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    row = next(
        (r for r in data if r.get("object_identifier") == "analog-input,1"), data[0]
    )
    assert row["bacnet_device_id"] == "3456789"
    assert row["object_identifier"] == "analog-input,1"
    assert row.get("object_name") == "SA-T"
    assert "point_id" in row


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
            "bacnet_device_id": None,
            "object_identifier": None,
            "object_name": None,
            "polling": True,
        }
    ]
    with (
        patch(
            "open_fdd.platform.api.data_model.serialize_to_ttl",
            return_value="@prefix brick: <https://brickschema.org/schema/Brick#> .\n",
        ),
        patch(
            "open_fdd.platform.api.data_model.get_conn",
            side_effect=lambda: _mock_conn_with_cursor(rows),
        ),
    ):
        r = client.get("/data-model/export")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["external_id"] == "SA-T"
    assert data[0]["point_id"] == str(point_id)
    assert data[0]["brick_type"] == "Supply_Air_Temperature_Sensor"
    assert data[0]["rule_input"] == "sat"


def test_data_model_export_includes_bacnet_refs():
    """Export includes bacnet_device_id, object_identifier, object_name for LLM/AI tagging workflow."""
    site_id = uuid4()
    point_id = uuid4()
    rows = [
        {
            "id": point_id,
            "site_id": site_id,
            "site_name": "Office",
            "external_id": "SA-T",
            "equipment_id": None,
            "equipment_name": None,
            "brick_type": None,
            "fdd_input": None,
            "unit": "degF",
            "bacnet_device_id": "3456789",
            "object_identifier": "analog-input,1",
            "object_name": "Supply Air Temp",
            "polling": True,
        }
    ]
    with (
        patch(
            "open_fdd.platform.api.data_model.serialize_to_ttl",
            return_value="@prefix brick: <https://brickschema.org/schema/Brick#> .\n",
        ),
        patch(
            "open_fdd.platform.api.data_model.get_conn",
            side_effect=lambda: _mock_conn_with_cursor(rows),
        ),
    ):
        r = client.get("/data-model/export")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["bacnet_device_id"] == "3456789"
    assert data[0]["object_identifier"] == "analog-input,1"
    assert data[0]["object_name"] == "Supply Air Temp"
    assert data[0]["point_id"] == str(point_id)


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
            {
                "point_id": str(uuid4()),
                "brick_type": "Supply_Air_Temperature_Sensor",
                "rule_input": "sat",
            }
        ]
    }
    with (
        patch("open_fdd.platform.api.data_model.get_conn", side_effect=lambda: conn),
        patch("open_fdd.platform.api.data_model.sync_ttl_to_file"),
    ):
        r = client.put("/data-model/import", json=body)
    assert r.status_code == 200
    data = r.json()
    assert "updated" in data
    assert "total" in data
    assert data["total"] == 1


def test_data_model_import_accepts_fdd_input_deprecated():
    """Backward compat: fdd_input still works, maps to rule_input."""
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
            {
                "point_id": str(uuid4()),
                "brick_type": "Cooling_Valve_Command",
                "fdd_input": "CLG-O",
            }
        ]
    }
    with (
        patch("open_fdd.platform.api.data_model.get_conn", side_effect=lambda: conn),
        patch("open_fdd.platform.api.data_model.sync_ttl_to_file"),
    ):
        r = client.put("/data-model/import", json=body)
    assert r.status_code == 200


def test_data_model_import_rejects_placeholder_site_id():
    """Import returns 400 when site_id is a placeholder (e.g. SITE_UUID) instead of a real UUID."""
    body = {
        "points": [
            {
                "point_id": None,
                "site_id": "SITE_UUID",
                "external_id": "DAP-P",
                "bacnet_device_id": "3456789",
                "object_identifier": "analog-input,1",
                "object_name": "DAP-P",
            }
        ]
    }
    with patch(
        "open_fdd.platform.api.data_model.get_conn",
        side_effect=lambda: _mock_conn_with_cursor([]),
    ):
        r = client.put("/data-model/import", json=body)
    assert r.status_code == 400
    detail = r.json().get("detail", "")
    if isinstance(detail, list):
        detail = " ".join(str(d) for d in detail)
    assert "site_id" in detail
    assert "SITE_UUID" in detail


def _sample_object_names_from_point_discovery_response(
    pdg_response: dict, max_names: int = 5
) -> list[str]:
    """Extract up to max_names unique object names from point_discovery_to_graph response (e2e contract)."""
    body = pdg_response.get("body") if isinstance(pdg_response, dict) else pdg_response
    res = body.get("result") if isinstance(body, dict) else {}
    data = (res.get("data") or res) if isinstance(res, dict) else {}
    objs = data.get("objects") or []
    names = []
    for o in objs[: max_names * 2]:  # look at a few more in case of blanks/dupes
        if isinstance(o, dict):
            n = (o.get("object_name") or o.get("name") or "").strip()
            if n and n not in names:
                names.append(n)
                if len(names) >= max_names:
                    break
    return names


def test_sample_object_names_from_point_discovery_response():
    """Parsing point_discovery_to_graph response yields up to 5 unique object names (e2e contract)."""
    assert _sample_object_names_from_point_discovery_response({}) == []
    assert _sample_object_names_from_point_discovery_response({"body": {}}) == []
    assert (
        _sample_object_names_from_point_discovery_response(
            {"body": {"result": {"data": {"objects": []}}}}
        )
        == []
    )
    assert _sample_object_names_from_point_discovery_response(
        {
            "body": {
                "result": {
                    "data": {
                        "objects": [
                            {"object_name": "SA-T"},
                            {"object_name": "ZoneTemp"},
                        ]
                    }
                }
            }
        }
    ) == ["SA-T", "ZoneTemp"]
    assert _sample_object_names_from_point_discovery_response(
        {"body": {"result": {"data": {"objects": [{"name": "DAP-P"}]}}}},
        max_names=5,
    ) == ["DAP-P"]
    # duplicates and blanks skipped; cap at max
    r = {
        "body": {
            "result": {
                "data": {
                    "objects": [
                        {"object_name": "A"},
                        {"object_name": ""},
                        {"object_name": "A"},
                        {"object_name": "B"},
                        {"object_name": "C"},
                        {"object_name": "D"},
                        {"object_name": "E"},
                    ]
                }
            }
        }
    }
    assert _sample_object_names_from_point_discovery_response(r, max_names=5) == [
        "A",
        "B",
        "C",
        "D",
        "E",
    ]


_BACNET_TTL_FOR_SPARQL = """@prefix bacnet: <http://data.ashrae.org/bacnet/2020#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<bacnet://3456789> a bacnet:Device ;
    bacnet:device-instance 3456789 ;
    bacnet:contains <bacnet://3456789/analog-input,1>, <bacnet://3456789/analog-input,2> .
<bacnet://3456789/analog-input,1> bacnet:object-name "SA-T" .
<bacnet://3456789/analog-input,2> bacnet:object-name "ZoneTemp" .
"""


def test_sparql_bacnet_device_and_object_names():
    """SPARQL over TTL that contains BACnet returns Device and object-name bindings (e2e graph path)."""
    with patch(
        "open_fdd.platform.api.data_model.get_ttl_for_sparql",
        return_value=_BACNET_TTL_FOR_SPARQL,
    ):
        r = client.post(
            "/data-model/sparql",
            json={
                "query": """
                PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
                SELECT ?dev WHERE { ?dev a bacnet:Device }
                """,
            },
        )
    assert r.status_code == 200
    bindings = r.json().get("bindings") or []
    assert len(bindings) >= 1
    assert any("dev" in b for b in bindings)

    with patch(
        "open_fdd.platform.api.data_model.get_ttl_for_sparql",
        return_value=_BACNET_TTL_FOR_SPARQL,
    ):
        r2 = client.post(
            "/data-model/sparql",
            json={
                "query": """
                PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
                SELECT ?name WHERE {
                  ?dev a bacnet:Device ; bacnet:device-instance 3456789 ; bacnet:contains ?obj .
                  ?obj bacnet:object-name ?name .
                }
                """,
            },
        )
    assert r2.status_code == 200
    names = [
        b.get("name") or "" for b in (r2.json().get("bindings") or []) if b.get("name")
    ]
    assert "SA-T" in names
    assert "ZoneTemp" in names
