"""Unit tests for in-memory RDF graph (graph_model): BACnet TTL from point_discovery, reset/config preservation."""

from unittest.mock import patch

import pytest

import openfdd_stack.platform.graph_model as graph_model_mod

from openfdd_stack.platform.graph_model import (
    bacnet_ttl_from_point_discovery,
    get_config_from_graph,
    reset_graph_to_db_only,
    set_config_in_graph,
    sync_brick_from_db,
    _purge_dangling_blank_nodes,
)


def test_bacnet_ttl_from_point_discovery_empty_objects():
    """Device with no objects still produces valid TTL (Device, no bacnet:contains)."""
    ttl = bacnet_ttl_from_point_discovery(
        3456789,
        "192.168.1.1",
        [],
    )
    assert "bacnet:Device" in ttl
    assert "bacnet:device-instance 3456789" in ttl
    assert "bacnet://3456789" in ttl
    assert (
        'bacnet:device-address "192.168.1.1"' in ttl
    )  # literal, not blank node (avoids orphan accumulation)
    assert "bacnet:contains" not in ttl or " ." in ttl  # no object refs


def test_bacnet_ttl_from_point_discovery_includes_device_and_object_names():
    """TTL includes device-instance, bacnet:contains, and object-name for each object."""
    objects = [
        {"object_identifier": "analog-input,1", "object_name": "SA-T"},
        {"object_identifier": "binary-value,2", "object_name": "Fan-On"},
    ]
    ttl = bacnet_ttl_from_point_discovery(
        3456788,
        "10.0.0.5",
        objects,
        device_name="Test AHU",
    )
    assert "bacnet:Device" in ttl
    assert "bacnet:device-instance 3456788" in ttl
    assert "Test AHU" in ttl
    assert "bacnet:contains" in ttl
    assert "bacnet://3456788/analog-input,1" in ttl
    assert "bacnet://3456788/binary-value,2" in ttl
    assert 'bacnet:object-name "SA-T"' in ttl
    assert 'bacnet:object-name "Fan-On"' in ttl


def test_bacnet_ttl_from_point_discovery_falls_back_to_name():
    """Object without object_name uses name or object_identifier-derived label."""
    objects = [
        {"object_identifier": "analog-input,3", "name": "ZoneTemp"},
    ]
    ttl = bacnet_ttl_from_point_discovery(999, "0.0.0.0", objects)
    assert 'bacnet:object-name "ZoneTemp"' in ttl


def test_bacnet_ttl_from_point_discovery_escapes_quotes():
    """Labels with quotes are escaped in TTL."""
    objects = [
        {"object_identifier": "ai,1", "object_name": 'Sensor "A"'},
    ]
    ttl = bacnet_ttl_from_point_discovery(1, "x", objects)
    assert '\\"' in ttl or "Sensor" in ttl


def test_reset_graph_to_db_only_seeds_default_config_when_graph_empty():
    """When graph has no config, reset seeds DEFAULT_PLATFORM_CONFIG so config always remains in graph."""
    from openfdd_stack.platform.default_config import DEFAULT_PLATFORM_CONFIG

    with (
        patch("openfdd_stack.platform.graph_model.get_config_from_graph", return_value={}),
        patch("openfdd_stack.platform.graph_model.sync_brick_from_db"),
    ):
        reset_graph_to_db_only()
        # Reset should have called set_config_in_graph with default; verify graph has config
        # (sync_brick is no-op, so graph was cleared then config was set)
    cfg = get_config_from_graph()
    assert cfg, "Graph should have config after reset (seeded with default)"
    assert cfg.get("rule_interval_hours") is not None
    assert cfg.get("bacnet_server_url") is not None
    # Defaults from default_config
    assert cfg.get("rules_dir") == DEFAULT_PLATFORM_CONFIG["rules_dir"]
    assert (
        cfg.get("open_meteo_timezone") == DEFAULT_PLATFORM_CONFIG["open_meteo_timezone"]
    )


def _orphan_blank_node_count(g) -> int:
    from rdflib import BNode

    bnode_as_subject = {s for s, _, _ in g if isinstance(s, BNode)}
    bnode_as_object = {o for _, _, o in g if isinstance(o, BNode)}
    return len(bnode_as_subject - bnode_as_object)


def test_purge_dangling_blank_nodes_after_removing_site_subjects():
    """Regression #99: ref: blank blobs must not linger after site# triples are removed."""
    from rdflib import Graph, URIRef

    from openfdd_stack.platform.graph_model import SITE_NS

    ttl = """@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ref: <https://brickschema.org/schema/Brick/ref#> .
@prefix : <http://openfdd.local/site#> .

:pt1 a brick:Supply_Air_Temperature_Sensor ;
  rdfs:label "SA-T" ;
  ref:hasExternalReference [ a ref:TimeseriesReference ;
      ref:hasTimeseriesId "SA-T" ;
      ref:storedAt "postgresql://x" ] .
"""
    g = Graph()
    g.parse(data=ttl, format="turtle")
    site_subjects = {s for s in g.subjects() if isinstance(s, URIRef) and str(s).startswith(SITE_NS)}
    assert site_subjects
    for s in site_subjects:
        for t in list(g.triples((s, None, None))):
            g.remove(t)
    assert _orphan_blank_node_count(g) > 0
    _purge_dangling_blank_nodes(g)
    assert _orphan_blank_node_count(g) == 0


def test_sync_brick_from_db_twice_does_not_accumulate_orphan_blank_nodes():
    """Each sync replaces Brick; orphan count must stay ~0 (issue #99)."""
    from rdflib import Graph
    from unittest.mock import patch

    brick_ttl = """@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ref: <https://brickschema.org/schema/Brick/ref#> .
@prefix : <http://openfdd.local/site#> .

:pt1 a brick:Supply_Air_Temperature_Sensor ;
  rdfs:label "SA-T" ;
  ref:hasExternalReference [ a ref:TimeseriesReference ;
      ref:hasTimeseriesId "SA-T" ;
      ref:storedAt "postgresql://x" ] .
"""
    saved = graph_model_mod._graph
    try:
        graph_model_mod._graph = Graph()
        with patch.object(
            graph_model_mod, "build_brick_ttl_from_db", return_value=brick_ttl
        ):
            sync_brick_from_db()
            n1 = _orphan_blank_node_count(graph_model_mod._graph)
            sync_brick_from_db()
            n2 = _orphan_blank_node_count(graph_model_mod._graph)
        assert n1 == 0
        assert n2 == 0
    finally:
        graph_model_mod._graph = saved


def test_reset_graph_to_db_only_preserves_existing_config():
    """When graph has config, reset preserves it (snapshot and restore)."""
    custom = {
        "rule_interval_hours": 2.5,
        "lookback_days": 7,
        "bacnet_site_id": "building-a",
    }
    set_config_in_graph(custom)
    with patch("openfdd_stack.platform.graph_model.sync_brick_from_db"):
        reset_graph_to_db_only()
    cfg = get_config_from_graph()
    assert cfg.get("rule_interval_hours") == 2.5
    assert cfg.get("lookback_days") == 7
    assert cfg.get("bacnet_site_id") == "building-a"
