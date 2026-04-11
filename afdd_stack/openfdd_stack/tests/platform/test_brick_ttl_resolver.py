"""Brick TTL → column_map (stack-only, rdflib)."""

from pathlib import Path

import pytest

pytest.importorskip("rdflib")

from open_fdd.engine.column_map_resolver import ColumnMapResolver
from openfdd_stack.platform.brick_ttl_resolver import (
    BrickTtlColumnMapResolver,
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
    ttl_file = tmp_path / "brick.ttl"
    ttl_file.write_text(_MINIMAL_TTL)
    mapping = resolve_from_ttl(ttl_file)
    assert "Supply_Air_Temperature_Sensor" in mapping
    assert mapping["Supply_Air_Temperature_Sensor"] == "sat"
    assert "Outside_Air_Temperature_Sensor" in mapping
    assert mapping["Outside_Air_Temperature_Sensor"] == "oat"


def test_resolve_from_ttl_accepts_str_path(tmp_path):
    ttl_file = tmp_path / "brick.ttl"
    ttl_file.write_text(_MINIMAL_TTL)
    mapping = resolve_from_ttl(str(ttl_file))
    assert mapping["Supply_Air_Temperature_Sensor"] == "sat"


def test_get_equipment_types_from_ttl_returns_types(tmp_path):
    ttl_file = tmp_path / "brick.ttl"
    ttl_file.write_text(_MINIMAL_TTL)
    types = get_equipment_types_from_ttl(ttl_file)
    assert "AHU" in types
    assert "VAV" in types
    assert len(types) == 2


def test_resolve_from_ttl_disambiguation_with_maps_to_rule_input(tmp_path):
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


def test_brick_ttl_column_map_resolver_matches_resolve_from_ttl(tmp_path):
    ttl_file = tmp_path / "model.ttl"
    ttl_file.write_text(_MINIMAL_TTL)
    assert BrickTtlColumnMapResolver().build_column_map(ttl_path=ttl_file) == resolve_from_ttl(
        ttl_file
    )


def test_brick_ttl_column_map_resolver_empty_when_ttl_missing(tmp_path):
    missing = tmp_path / "nope.ttl"
    assert not missing.exists()
    assert BrickTtlColumnMapResolver().build_column_map(ttl_path=missing) == {}


def test_brick_ttl_resolver_satisfies_open_fdd_protocol():
    assert isinstance(BrickTtlColumnMapResolver(), ColumnMapResolver)
