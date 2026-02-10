"""Unit tests for data model TTL generation from DB (API/sql sync)."""

from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest

from open_fdd.platform.data_model_ttl import build_ttl_from_db, _escape, _prefixes


def _mock_cursor(sites, equipment, points):
    cursor = MagicMock()
    fetch_results = [sites, equipment, points]
    cursor.fetchall.side_effect = fetch_results
    return cursor


def _mock_conn(cursor):
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    return conn


def test_prefixes():
    p = _prefixes()
    assert "@prefix brick:" in p
    assert "brickschema.org" in p
    assert "ofdd:" in p


def test_escape():
    assert _escape("SA-T") == "SA-T"
    assert _escape('say "hi"') == 'say \\"hi\\"'
    assert _escape(None) == ""


def test_build_ttl_empty_db():
    cursor = _mock_cursor([], [], [])
    conn = _mock_conn(cursor)
    with patch("open_fdd.platform.data_model_ttl.get_conn", return_value=conn):
        ttl = build_ttl_from_db()
    assert ttl.strip().startswith("@prefix")
    assert "brick:Site" not in ttl or ttl.count("brick:Site") == 0


def test_build_ttl_one_site_one_point():
    site_id = uuid4()
    point_id = uuid4()
    sites = [{"id": site_id, "name": "Default"}]
    equipment = []
    points = [
        {
            "id": point_id,
            "site_id": site_id,
            "external_id": "SA-T",
            "brick_type": "Supply_Air_Temperature_Sensor",
            "fdd_input": "sat",
            "unit": "degF",
            "equipment_id": None,
        }
    ]
    cursor = _mock_cursor(sites, equipment, points)
    conn = _mock_conn(cursor)
    with patch("open_fdd.platform.data_model_ttl.get_conn", return_value=conn):
        ttl = build_ttl_from_db()
    assert "brick:Site" in ttl
    assert "Default" in ttl
    assert "SA-T" in ttl
    assert "Supply_Air_Temperature_Sensor" in ttl
    assert "sat" in ttl
    assert "ofdd:mapsToRuleInput" in ttl
    assert "rdfs:label" in ttl


def test_build_ttl_site_with_equipment_and_points():
    site_id = uuid4()
    eq_id = uuid4()
    pt_id = uuid4()
    sites = [{"id": site_id, "name": "Building A"}]
    equipment = [
        {"id": eq_id, "site_id": site_id, "name": "AHU-1", "equipment_type": "AHU"}
    ]
    points = [
        {
            "id": pt_id,
            "site_id": site_id,
            "external_id": "DAP-P",
            "brick_type": "Supply_Air_Static_Pressure_Sensor",
            "fdd_input": None,
            "unit": "inH2O",
            "equipment_id": eq_id,
        }
    ]
    cursor = _mock_cursor(sites, equipment, points)
    conn = _mock_conn(cursor)
    with patch("open_fdd.platform.data_model_ttl.get_conn", return_value=conn):
        ttl = build_ttl_from_db()
    assert "brick:Site" in ttl
    assert "Building A" in ttl
    assert "brick:AHU" in ttl
    assert "AHU-1" in ttl
    assert "DAP-P" in ttl
    assert "Supply_Air_Static_Pressure_Sensor" in ttl
    assert "brick:isPointOf" in ttl
    assert "brick:isPartOf" in ttl
