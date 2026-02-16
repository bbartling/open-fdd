"""Unit tests for Brick resolver (SPARQL-driven column mapping from TTL)."""

from pathlib import Path

import pytest

pytest.importorskip("rdflib")
from open_fdd.engine.brick_resolver import (
    get_equipment_types_from_ttl,
    resolve_from_ttl,
)

_MINIMAL_TTL = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ofdd: <http://openfdd.local/ontology#> .

<http://openfdd.local/point/sat> a brick:Supply_Air_Temperature_Sensor ;
    rdfs:label "sat" .

<http://openfdd.local/point/oat> a brick:Outside_Air_Temperature_Sensor ;
    rdfs:label "oat" .

<http://openfdd.local/equipment/ahu1> ofdd:equipmentType "AHU" .
<http://openfdd.local/equipment/vav1> ofdd:equipmentType "VAV" .
"""


def test_resolve_from_ttl_returns_column_map(tmp_path):
    """resolve_from_ttl loads TTL, runs SPARQL, returns Brick class -> external_id (label) map."""
    ttl_file = tmp_path / "brick.ttl"
    ttl_file.write_text(_MINIMAL_TTL)
    mapping = resolve_from_ttl(ttl_file)
    assert "Supply_Air_Temperature_Sensor" in mapping
    assert mapping["Supply_Air_Temperature_Sensor"] == "sat"
    assert "Outside_Air_Temperature_Sensor" in mapping
    assert mapping["Outside_Air_Temperature_Sensor"] == "oat"


def test_resolve_from_ttl_accepts_str_path(tmp_path):
    """resolve_from_ttl accepts str path as well as Path."""
    ttl_file = tmp_path / "brick.ttl"
    ttl_file.write_text(_MINIMAL_TTL)
    mapping = resolve_from_ttl(str(ttl_file))
    assert mapping["Supply_Air_Temperature_Sensor"] == "sat"


def test_get_equipment_types_from_ttl_returns_types(tmp_path):
    """get_equipment_types_from_ttl runs SPARQL, returns distinct equipment types."""
    ttl_file = tmp_path / "brick.ttl"
    ttl_file.write_text(_MINIMAL_TTL)
    types = get_equipment_types_from_ttl(ttl_file)
    assert "AHU" in types
    assert "VAV" in types
    assert len(types) == 2


def test_resolve_from_ttl_disambiguation_with_maps_to_rule_input(tmp_path):
    """When same Brick class appears twice, ofdd:mapsToRuleInput disambiguates; composite key used."""
    ttl_with_dupe = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ofdd: <http://openfdd.local/ontology#> .

<http://openfdd.local/point/v1> a brick:Valve_Command ; rdfs:label "v_cmd_1" ; ofdd:mapsToRuleInput "reheat" .
<http://openfdd.local/point/v2> a brick:Valve_Command ; rdfs:label "v_cmd_2" ; ofdd:mapsToRuleInput "cooling" .
"""
    ttl_file = tmp_path / "brick.ttl"
    ttl_file.write_text(ttl_with_dupe)
    mapping = resolve_from_ttl(ttl_file)
    assert mapping.get("Valve_Command|reheat") == "v_cmd_1"
    assert mapping.get("Valve_Command|cooling") == "v_cmd_2"
    assert mapping.get("reheat") == "v_cmd_1"
    assert mapping.get("cooling") == "v_cmd_2"
