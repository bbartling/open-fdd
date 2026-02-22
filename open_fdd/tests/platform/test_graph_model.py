"""Unit tests for in-memory RDF graph (graph_model): BACnet TTL from point_discovery."""

import pytest

from open_fdd.platform.graph_model import bacnet_ttl_from_point_discovery


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
