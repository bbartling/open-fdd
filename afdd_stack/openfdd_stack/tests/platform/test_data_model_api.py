"""Unit tests for data-model API (export, import, TTL, SPARQL) — validates API/sql/data-model sync."""

from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from openfdd_stack.platform.api.main import app

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


def _mock_get_conn_sequence(*fetchall_batches):
    """Simulate sequential DB connections: each get_conn() uses the next fetchall list."""

    batches = list(fetchall_batches)

    def get_conn():
        batch = batches.pop(0) if batches else []
        return _mock_conn_with_cursor(batch)

    return get_conn


def test_data_model_export_empty():
    with (
        patch(
            "openfdd_stack.platform.api.data_model.serialize_to_ttl",
            return_value="@prefix brick: <https://brickschema.org/schema/Brick#> .\n",
        ),
        patch(
            "openfdd_stack.platform.api.data_model.get_conn",
            side_effect=_mock_get_conn_sequence([], []),
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
            "openfdd_stack.platform.api.data_model.serialize_to_ttl",
            return_value=minimal_bacnet_ttl,
        ),
        patch(
            "openfdd_stack.platform.api.data_model.get_conn",
            side_effect=_mock_get_conn_sequence([], [], []),
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
            "openfdd_stack.platform.api.data_model.serialize_to_ttl",
            return_value="@prefix brick: <https://brickschema.org/schema/Brick#> .\n",
        ),
        patch(
            "openfdd_stack.platform.api.data_model.get_conn",
            side_effect=_mock_get_conn_sequence([], rows),
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
            "openfdd_stack.platform.api.data_model.serialize_to_ttl",
            return_value="@prefix brick: <https://brickschema.org/schema/Brick#> .\n",
        ),
        patch(
            "openfdd_stack.platform.api.data_model.get_conn",
            side_effect=_mock_get_conn_sequence([], rows),
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


def test_data_model_export_unimported_discovery_prefills_site_when_single_site_in_db():
    """Without ?site_id=, discovery-only rows still get site_id when the DB has exactly one site."""
    only_site_id = uuid4()
    minimal_bacnet_ttl = """
@prefix bacnet: <http://data.ashrae.org/bacnet/2020#> .
@prefix rdfs: <http://www.w3.org/2000/rdf-schema#> .
<bacnet://3456789> a bacnet:Device ;
    rdfs:label "AHU1" ;
    bacnet:device-instance 3456789 ;
    bacnet:contains <bacnet://3456789/analog-input,1> .
<bacnet://3456789/analog-input,1> bacnet:object-identifier "analog-input,1" ;
    bacnet:object-name "SA-T" .
"""
    with (
        patch(
            "openfdd_stack.platform.api.data_model.serialize_to_ttl",
            return_value=minimal_bacnet_ttl,
        ),
        patch(
            "openfdd_stack.platform.api.data_model.get_conn",
            side_effect=_mock_get_conn_sequence(
                [{"id": only_site_id, "name": "BenchSite"}],
                [],
                [],
            ),
        ),
    ):
        r = client.get("/data-model/export?bacnet_only=true")
    assert r.status_code == 200
    data = r.json()
    row = next(x for x in data if x.get("object_identifier") == "analog-input,1")
    assert row["point_id"] is None
    assert row["site_id"] == str(only_site_id)
    assert row["site_name"] == "BenchSite"


def test_data_model_export_includes_equipment_engineering_metadata():
    site_id = uuid4()
    point_id = uuid4()
    equipment_id = uuid4()
    rows = [
        {
            "id": point_id,
            "site_id": site_id,
            "site_name": "Office",
            "external_id": "SA-T",
            "equipment_id": equipment_id,
            "equipment_name": "AHU-1",
            "equipment_metadata": {
                "engineering": {"mechanical": {"design_cfm": 5000}},
                "unknown_custom": {"x": 1},
            },
            "brick_type": "Supply_Air_Temperature_Sensor",
            "fdd_input": "sat",
            "unit": "degF",
            "bacnet_device_id": "3456789",
            "object_identifier": "analog-input,1",
            "object_name": "Supply Air Temp",
            "polling": True,
        }
    ]
    with (
        patch(
            "openfdd_stack.platform.api.data_model.serialize_to_ttl",
            return_value="@prefix brick: <https://brickschema.org/schema/Brick#> .\n",
        ),
        patch(
            "openfdd_stack.platform.api.data_model.get_conn",
            side_effect=_mock_get_conn_sequence([], rows),
        ),
    ):
        r = client.get("/data-model/export")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["engineering"]["mechanical"]["design_cfm"] == 5000
    assert data[0]["equipment_metadata"]["unknown_custom"]["x"] == 1


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
    cursor.fetchall.side_effect = [sites, equipment, points, []]
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    with patch("openfdd_stack.platform.data_model_ttl.get_conn", return_value=conn):
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
    cursor.fetchall.side_effect = [sites, equipment, points, []]
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    query = "PREFIX brick: <https://brickschema.org/schema/Brick#> SELECT ?s WHERE { ?s a brick:Site } LIMIT 1"
    with patch("openfdd_stack.platform.data_model_ttl.get_conn", return_value=conn):
        r = client.post("/data-model/sparql", json={"query": query})
    assert r.status_code == 200
    data = r.json()
    assert "bindings" in data
    assert isinstance(data["bindings"], list)
    if data["bindings"]:
        assert "s" in data["bindings"][0]


def test_data_model_import_update_by_point_id_applies_equipment_name():
    """LLM-tagged export rows have point_id; equipment_name must still create/link equipment."""
    site_id = uuid4()
    point_id = uuid4()
    vav_equipment_id = str(uuid4())
    cursor = MagicMock()
    cursor.rowcount = 1
    cursor.execute.return_value = None
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    cursor.fetchall.return_value = [{"id": site_id}]
    body = {
        "points": [
            {
                "point_id": str(point_id),
                "site_id": str(site_id),
                "equipment_name": "VAV-1",
            }
        ]
    }
    with (
        patch("openfdd_stack.platform.api.data_model.get_conn", side_effect=lambda: conn),
        patch(
            "openfdd_stack.platform.api.data_model._ensure_equipment",
            return_value=vav_equipment_id,
        ) as mock_ensure,
        patch("openfdd_stack.platform.api.data_model.sync_ttl_to_file"),
    ):
        r = client.put("/data-model/import", json=body)
    assert r.status_code == 200
    mock_ensure.assert_called_once()
    update_sqls = [
        c.args[0]
        for c in cursor.execute.call_args_list
        if c.args and isinstance(c.args[0], str) and "UPDATE points SET" in c.args[0]
    ]
    assert any("equipment_id = %s" in s for s in update_sqls)


def test_data_model_import_rejects_unknown_top_level_keys():
    """DataModelImportBody uses extra=forbid — LLM payloads must not add sites/relationships/etc."""
    body = {
        "points": [
            {
                "point_id": str(uuid4()),
                "brick_type": "Supply_Air_Temperature_Sensor",
                "rule_input": "sat",
            }
        ],
        "sites": [],
    }
    r = client.put("/data-model/import", json=body)
    assert r.status_code == 422


def test_data_model_import_explicit_null_modbus_config_clears_column():
    """JSON null for modbus_config clears the DB column; omitting the key would leave it unchanged."""
    site_id = uuid4()
    point_id = uuid4()
    cursor = MagicMock()
    cursor.rowcount = 1
    cursor.execute.return_value = None
    cursor.fetchall.return_value = [{"id": site_id}]
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    body = {
        "points": [
            {
                "point_id": str(point_id),
                "modbus_config": None,
            }
        ]
    }
    with (
        patch("openfdd_stack.platform.api.data_model.get_conn", side_effect=lambda: conn),
        patch("openfdd_stack.platform.api.data_model.sync_ttl_to_file"),
    ):
        r = client.put("/data-model/import", json=body)
    assert r.status_code == 200
    update_calls = [
        c
        for c in cursor.execute.call_args_list
        if c.args and isinstance(c.args[0], str) and "UPDATE points SET" in c.args[0]
    ]
    assert update_calls
    assert any(
        "modbus_config = %s" in c.args[0] and None in (c.args[1] if len(c.args) > 1 else ())
        for c in update_calls
    )


def test_data_model_import_invalid_modbus_float32_count_one_returns_422():
    """Non-empty modbus_config that fails normalize must fail the import (not 200 + silent skip)."""
    site_id = uuid4()
    point_id = uuid4()
    cursor = MagicMock()
    cursor.rowcount = 1
    cursor.execute.return_value = None
    cursor.fetchall.return_value = [{"id": site_id}]
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    body = {
        "points": [
            {
                "point_id": str(point_id),
                "site_id": str(site_id),
                "modbus_config": {
                    "host": "127.0.0.1",
                    "address": 0,
                    "count": 1,
                    "function": "holding",
                    "decode": "float32",
                },
            }
        ]
    }
    with (
        patch("openfdd_stack.platform.api.data_model.get_conn", side_effect=lambda: conn),
        patch("openfdd_stack.platform.api.data_model.sync_ttl_to_file"),
    ):
        r = client.put("/data-model/import", json=body)
    assert r.status_code == 422
    payload = r.json()
    msg = payload.get("detail") or (payload.get("error") or {}).get("message", "")
    assert isinstance(msg, str)
    assert "count >=" in msg


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
        patch("openfdd_stack.platform.api.data_model.get_conn", side_effect=lambda: conn),
        patch("openfdd_stack.platform.api.data_model.sync_ttl_to_file"),
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
        patch("openfdd_stack.platform.api.data_model.get_conn", side_effect=lambda: conn),
        patch("openfdd_stack.platform.api.data_model.sync_ttl_to_file"),
    ):
        r = client.put("/data-model/import", json=body)
    assert r.status_code == 200


def test_data_model_import_stale_point_id_falls_back_to_create():
    """If point_id does not exist, import should create by identity fields instead of silent no-op."""
    site_id = uuid4()
    cursor = MagicMock()
    # First update-by-point_id misses (rowcount 0), then insert succeeds (rowcount 1).
    def _execute(sql, params=None):
        if "UPDATE points SET" in sql and "WHERE id = %s" in sql:
            cursor.rowcount = 0
        elif "INSERT INTO points" in sql:
            cursor.rowcount = 1
        else:
            cursor.rowcount = 1
        return None

    cursor.execute.side_effect = _execute
    cursor.fetchall.return_value = [{"id": site_id}]
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    body = {
        "points": [
            {
                "point_id": str(uuid4()),
                "site_id": str(site_id),
                "external_id": "SA-T",
                "bacnet_device_id": "3456789",
                "object_identifier": "analog-input,2",
                "object_name": "SA-T",
                "brick_type": "Supply_Air_Temperature_Sensor",
                "rule_input": "sat",
            }
        ]
    }
    with (
        patch("openfdd_stack.platform.api.data_model.get_conn", side_effect=lambda: conn),
        patch("openfdd_stack.platform.api.data_model.sync_ttl_to_file"),
    ):
        r = client.put("/data-model/import", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["created"] == 1
    assert data["updated"] == 0
    reasons = [w.get("reason", "") for w in data.get("warnings", [])]
    assert any("point_id not found; created by identity fields" in s for s in reasons)


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
        "openfdd_stack.platform.api.data_model.get_conn",
        side_effect=lambda: _mock_conn_with_cursor([]),
    ):
        r = client.put("/data-model/import", json=body)
    assert r.status_code == 400
    detail = (r.json().get("error") or {}).get("message", "") or r.json().get(
        "detail", ""
    )
    if isinstance(detail, list):
        detail = " ".join(str(d) for d in detail)
    assert "site_id" in detail
    assert "SITE_UUID" in detail


def test_data_model_import_missing_site_returns_400():
    """Import returns 400 with clear message when point references a site_id not in the DB."""
    existing_site_id = uuid4()
    missing_site_id = uuid4()
    body = {
        "points": [
            {
                "point_id": None,
                "site_id": str(missing_site_id),
                "external_id": "SA-T",
                "bacnet_device_id": "1",
                "object_identifier": "ai,1",
                "object_name": "SA-T",
            }
        ]
    }
    with patch(
        "openfdd_stack.platform.api.data_model.get_conn",
        side_effect=lambda: _mock_conn_with_cursor([{"id": existing_site_id}]),
    ):
        r = client.put("/data-model/import", json=body)
    assert r.status_code == 400
    detail = (r.json().get("error") or {}).get("message", "") or str(r.json())
    assert "Missing site" in detail
    assert "add the site" in detail.lower() or "try again" in detail.lower()


def test_data_model_import_infers_payload_site_for_null_rows():
    """When payload has one explicit site_id, rows with null site_id should use that site."""
    inferred_site_id = uuid4()
    cursor = MagicMock()

    def _execute(sql, params=None):
        if "INSERT INTO points" in sql:
            cursor.rowcount = 1
        else:
            cursor.rowcount = 1
        return None

    cursor.execute.side_effect = _execute
    cursor.fetchall.return_value = [{"id": inferred_site_id}]
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    body = {
        "points": [
            {
                # Explicit site_id in one row lets import infer payload-level default.
                "site_id": str(inferred_site_id),
                "external_id": "existing-row",
                "bacnet_device_id": "1",
                "object_identifier": "ai,1",
                "object_name": "existing-row",
            },
            {
                # Null site_id still gets imported via inferred payload site.
                "site_id": None,
                "external_id": "SA-T",
                "bacnet_device_id": "3456789",
                "object_identifier": "analog-input,2",
                "object_name": "SA-T",
                "brick_type": "Supply_Air_Temperature_Sensor",
                "rule_input": "sat",
            },
        ]
    }
    with (
        patch("openfdd_stack.platform.api.data_model.get_conn", side_effect=lambda: conn),
        patch("openfdd_stack.platform.api.data_model.sync_ttl_to_file"),
    ):
        r = client.put("/data-model/import", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["created"] >= 1
    assert data["total"] == 2


def test_data_model_import_equipment_engineering_metadata_is_merged():
    site_id = uuid4()
    equipment_id = uuid4()
    cursor = MagicMock()

    def _execute(sql, params=None):
        if "SELECT metadata FROM equipment" in sql:
            cursor.fetchone.return_value = {"metadata": {"existing": 1}}
            cursor.rowcount = 1
            return None
        cursor.rowcount = 1
        return None

    cursor.execute.side_effect = _execute
    cursor.fetchall.return_value = [{"id": site_id}]
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    body = {
        "points": [],
        "equipment": [
            {
                "equipment_id": str(equipment_id),
                "site_id": str(site_id),
                "engineering": {"controls": {"control_vendor": "Acme"}},
                "metadata": {"custom_key": {"foo": "bar"}},
            }
        ],
    }
    with (
        patch("openfdd_stack.platform.api.data_model.get_conn", side_effect=lambda: conn),
        patch("openfdd_stack.platform.api.data_model.sync_ttl_to_file"),
    ):
        r = client.put("/data-model/import", json=body)
    assert r.status_code == 200
    # Ensure we wrote metadata JSON containing merged existing/custom/engineering keys.
    execute_calls = cursor.execute.call_args_list
    metadata_updates = [
        c
        for c in execute_calls
        if "UPDATE equipment SET metadata = %s::jsonb" in (c.args[0] if c.args else "")
    ]
    assert metadata_updates
    payload = metadata_updates[-1].args[1][0]
    assert '"existing": 1' in payload
    assert '"custom_key"' in payload
    assert '"engineering"' in payload


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
        "openfdd_stack.platform.api.data_model.get_ttl_for_sparql",
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
        "openfdd_stack.platform.api.data_model.get_ttl_for_sparql",
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
