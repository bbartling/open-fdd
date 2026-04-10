"""Unit tests for data model TTL generation from DB (API/sql sync)."""

from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest

from openfdd_stack.platform.data_model_ttl import build_ttl_from_db, _escape, _prefixes


def _mock_cursor(sites, equipment, points, energy_rows=None):
    cursor = MagicMock()
    er = [] if energy_rows is None else energy_rows
    fetch_results = [sites, equipment, points, er]
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
    assert "@prefix ref:" in p
    assert "@prefix bacnet:" in p


def test_escape():
    assert _escape("SA-T") == "SA-T"
    assert _escape('say "hi"') == 'say \\"hi\\"'
    assert _escape(None) == ""


def test_build_ttl_empty_db():
    cursor = _mock_cursor([], [], [])
    conn = _mock_conn(cursor)
    with patch("openfdd_stack.platform.data_model_ttl.get_conn", return_value=conn):
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
    with patch("openfdd_stack.platform.data_model_ttl.get_conn", return_value=conn):
        ttl = build_ttl_from_db()
    assert "brick:Site" in ttl
    assert "Default" in ttl
    assert "SA-T" in ttl
    assert "Supply_Air_Temperature_Sensor" in ttl
    assert "sat" in ttl
    assert "ofdd:mapsToRuleInput" in ttl
    assert "rdfs:label" in ttl
    assert "ofdd:unit" in ttl
    assert "degF" in ttl
    assert "ref:hasExternalReference" in ttl
    assert "ref:TimeseriesReference" in ttl
    assert 'ref:hasTimeseriesId "SA-T"' in ttl
    assert "ref:storedAt" in ttl


def test_build_ttl_point_with_modbus_config():
    site_id = uuid4()
    point_id = uuid4()
    sites = [{"id": site_id, "name": "Site-M"}]
    equipment = []
    mc = {"host": "192.168.1.10", "port": 502, "unit_id": 1, "address": 100, "function": "holding"}
    points = [
        {
            "id": point_id,
            "site_id": site_id,
            "external_id": "meter_kW",
            "brick_type": "Power_Sensor",
            "fdd_input": "meter_kw",
            "unit": "kW",
            "equipment_id": None,
            "polling": True,
            "bacnet_device_id": None,
            "object_identifier": None,
            "object_name": None,
            "modbus_config": mc,
        }
    ]
    cursor = _mock_cursor(sites, equipment, points)
    conn = _mock_conn(cursor)
    with patch("openfdd_stack.platform.data_model_ttl.get_conn", return_value=conn):
        ttl = build_ttl_from_db()
    assert "ofdd:modbusConfig" in ttl
    assert "192.168.1.10" in ttl
    assert "meter_kW" in ttl


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
    with patch("openfdd_stack.platform.data_model_ttl.get_conn", return_value=conn):
        ttl = build_ttl_from_db()
    assert "brick:Site" in ttl
    assert "Building A" in ttl
    assert "brick:AHU" in ttl
    assert "AHU-1" in ttl
    assert "DAP-P" in ttl
    assert "Supply_Air_Static_Pressure_Sensor" in ttl
    assert "brick:isPointOf" in ttl
    assert "brick:isPartOf" in ttl
    assert "ofdd:unit" in ttl
    assert "inH2O" in ttl
    assert "ref:TimeseriesReference" in ttl


def test_build_ttl_bacnet_external_reference_when_point_has_bacnet_fields():
    site_id = uuid4()
    pt_id = uuid4()
    sites = [{"id": site_id, "name": "BACnet Site"}]
    equipment = []
    points = [
        {
            "id": pt_id,
            "site_id": site_id,
            "external_id": "ZoneTemp",
            "brick_type": "Zone_Air_Temperature_Sensor",
            "fdd_input": None,
            "unit": "degF",
            "equipment_id": None,
            "bacnet_device_id": "123",
            "object_identifier": "analog-input,3",
            "object_name": "BLDG-Z410-ZATS",
        }
    ]
    cursor = _mock_cursor(sites, equipment, points)
    conn = _mock_conn(cursor)
    with patch("openfdd_stack.platform.data_model_ttl.get_conn", return_value=conn):
        ttl = build_ttl_from_db()
    assert "ref:BACnetReference" in ttl
    assert 'bacnet:object-identifier "analog-input,3"' in ttl
    assert 'bacnet:object-name "BLDG-Z410-ZATS"' in ttl
    assert 'brick:BACnetURI "bacnet://123/analog-input,3/present-value"' in ttl
    assert "bacnet:objectOf <bacnet://123>" in ttl


def test_build_ttl_point_without_unit_omits_ofdd_unit():
    """When point has no unit (None or missing), TTL must not contain ofdd:unit for that point."""
    site_id = uuid4()
    pt_id = uuid4()
    sites = [{"id": site_id, "name": "NoUnit"}]
    equipment = []
    points = [
        {
            "id": pt_id,
            "site_id": site_id,
            "external_id": "X",
            "brick_type": "Point",
            "fdd_input": None,
            "unit": None,
            "equipment_id": None,
        }
    ]
    cursor = _mock_cursor(sites, equipment, points)
    conn = _mock_conn(cursor)
    with patch("openfdd_stack.platform.data_model_ttl.get_conn", return_value=conn):
        ttl = build_ttl_from_db()
    assert "rdfs:label" in ttl
    assert 'rdfs:label "X"' in ttl
    assert "ofdd:unit" not in ttl


def test_build_ttl_one_subject_per_entity_no_duplicate_uris():
    """Serialized TTL has exactly one subject URI per site, per equipment, per point (no duplicates)."""
    site_id1 = uuid4()
    site_id2 = uuid4()
    eq_id = uuid4()
    pt_id = uuid4()
    sites = [
        {"id": site_id1, "name": "SiteA"},
        {"id": site_id2, "name": "SiteB"},
    ]
    equipment = [
        {"id": eq_id, "site_id": site_id1, "name": "AHU-1", "equipment_type": "AHU"}
    ]
    points = [
        {
            "id": pt_id,
            "site_id": site_id1,
            "external_id": "SA-T",
            "brick_type": "Point",
            "fdd_input": None,
            "unit": "degF",
            "equipment_id": eq_id,
        }
    ]
    cursor = _mock_cursor(sites, equipment, points)
    conn = _mock_conn(cursor)
    with patch("openfdd_stack.platform.data_model_ttl.get_conn", return_value=conn):
        ttl = build_ttl_from_db()
    # Each entity has a unique subject (:site_<uuid>, :eq_<uuid>, :pt_<uuid>); count type declarations
    assert ttl.count("a brick:Site") == 2
    assert ttl.count("a brick:AHU") == 1
    assert ttl.count("a brick:Point") == 1
    # Site URIs must be distinct (no duplicate site subjects)
    s1_ref = f":site_{str(site_id1).replace('-', '_')}"
    s2_ref = f":site_{str(site_id2).replace('-', '_')}"
    assert ttl.count(s1_ref) >= 1
    assert ttl.count(s2_ref) >= 1


def test_build_ttl_includes_engineering_extension_and_s223_topology():
    site_id = uuid4()
    eq_id = uuid4()
    sites = [{"id": site_id, "name": "EngSite"}]
    equipment = [
        {
            "id": eq_id,
            "site_id": site_id,
            "name": "AHU-1",
            "equipment_type": "Air_Handling_Unit",
            "metadata": {
                "engineering": {
                    "controls": {"control_vendor": "Acme"},
                    "mechanical": {"design_cfm": 5000},
                    "topology": {
                        "connection_points": [
                            {"id": "inlet-1", "name": "Inlet", "type": "inlet", "medium": "air"}
                        ],
                        "connections": [
                            {
                                "conduit_type": "duct",
                                "from": "inlet-1",
                                "to": "downstream-1",
                                "medium": "air",
                            }
                        ],
                    },
                }
            },
        }
    ]
    points = []
    cursor = _mock_cursor(sites, equipment, points)
    conn = _mock_conn(cursor)
    with patch("openfdd_stack.platform.data_model_ttl.get_conn", return_value=conn):
        ttl = build_ttl_from_db()
    assert "@prefix s223:" in ttl
    assert "ofdd:controlVendor" in ttl
    assert "ofdd:designCFM" in ttl
    assert "s223:hasConnectionPoint" in ttl
    assert "s223:Duct" in ttl


def test_build_ttl_includes_energy_calculation():
    site_id = uuid4()
    ec_id = uuid4()
    sites = [{"id": site_id, "name": "Energy Site"}]
    equipment = []
    points = []
    energy = [
        {
            "id": ec_id,
            "site_id": site_id,
            "equipment_id": None,
            "external_id": "oa_heat_1",
            "name": "Excess OA heat",
            "description": "Site-specific spec",
            "calc_type": "oa_heating_sensible",
            "parameters": {"cfm_excess": 1000},
            "point_bindings": {"cfm": "OA_FLOW"},
            "enabled": True,
        }
    ]
    cursor = _mock_cursor(sites, equipment, points, energy)
    conn = _mock_conn(cursor)
    with patch("openfdd_stack.platform.data_model_ttl.get_conn", return_value=conn):
        ttl = build_ttl_from_db()
    assert "ofdd:EnergyCalculation" in ttl
    assert "oa_heat_1" in ttl
    assert "oa_heating_sensible" in ttl
    assert "brick:isPartOf" in ttl


def test_build_ttl_energy_calc_includes_penalty_catalog_seq():
    site_id = uuid4()
    ec_id = uuid4()
    sites = [{"id": site_id, "name": "P Site"}]
    equipment = []
    points = []
    energy = [
        {
            "id": ec_id,
            "site_id": site_id,
            "equipment_id": None,
            "external_id": "penalty_default_01",
            "name": "Out-of-schedule",
            "description": "x",
            "calc_type": "runtime_electric_kw",
            "parameters": {"_penalty_catalog_seq": 1, "kw": 1},
            "point_bindings": {},
            "enabled": False,
        }
    ]
    cursor = _mock_cursor(sites, equipment, points, energy)
    conn = _mock_conn(cursor)
    with patch("openfdd_stack.platform.data_model_ttl.get_conn", return_value=conn):
        ttl = build_ttl_from_db()
    assert "ofdd:penaltyCatalogSeq 1" in ttl
