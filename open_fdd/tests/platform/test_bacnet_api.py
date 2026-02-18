"""Tests for BACnet API (proxy routes and point_discovery_to_graph)."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app
from open_fdd.platform.data_model_ttl import parse_bacnet_ttl_to_discovery

client = TestClient(app)

_MINIMAL_BACNET_TTL = """@prefix bacnet: <http://data.ashrae.org/bacnet/2020#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<bacnet://3456789> a bacnet:Device ;
    bacnet:device-instance 3456789 ;
    bacnet:contains <bacnet://3456789/analog-input,1>, <bacnet://3456789/device,3456789> .
<bacnet://3456789/analog-input,1> bacnet:object-identifier "analog-input,1" ;
    bacnet:object-name "DAP-P" .
<bacnet://3456789/device,3456789> bacnet:object-identifier "device,3456789" ;
    bacnet:object-name "BensFakeAhu" .
"""


def test_parse_bacnet_ttl_to_discovery():
    """parse_bacnet_ttl_to_discovery extracts devices and point_discoveries from TTL."""
    devices, point_discoveries = parse_bacnet_ttl_to_discovery(_MINIMAL_BACNET_TTL)
    assert len(devices) == 1
    assert devices[0]["device_instance"] == 3456789
    assert devices[0]["name"] == "BensFakeAhu"
    assert len(point_discoveries) == 1
    assert point_discoveries[0]["device_instance"] == 3456789
    objs = point_discoveries[0]["objects"]
    assert len(objs) == 2
    oids = {o["object_identifier"] for o in objs}
    assert "analog-input,1" in oids
    assert "device,3456789" in oids
    names = {o["object_name"] for o in objs}
    assert "DAP-P" in names
    assert "BensFakeAhu" in names
