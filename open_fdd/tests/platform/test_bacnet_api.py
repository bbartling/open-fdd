"""Tests for BACnet API (proxy routes and discovery-to-rdf with import_into_data_model)."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

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


def test_discovery_to_rdf_with_import_into_data_model():
    """POST /bacnet/discovery-to-rdf with import_into_data_model creates points and returns import_result."""
    site_uuid = uuid4()
    eq_uuid = uuid4()

    def mock_cursor():
        cur = MagicMock()
        cur.execute.return_value = None
        cur.fetchone.side_effect = [None, {"id": eq_uuid}]
        return cur

    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(
        side_effect=[mock_cursor(), mock_cursor()]
    )
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    conn.commit = MagicMock()

    def fake_post_rpc(*args, **kwargs):
        return {
            "ok": True,
            "status_code": 200,
            "body": {
                "jsonrpc": "2.0",
                "result": {
                    "ttl": _MINIMAL_BACNET_TTL,
                    "summary": {"devices": 1, "objects": 2},
                },
                "id": "0",
            },
        }

    with (
        patch("open_fdd.platform.api.bacnet._post_rpc", side_effect=fake_post_rpc),
        patch("open_fdd.platform.api.bacnet.get_conn", side_effect=lambda: conn),
        patch("open_fdd.platform.api.bacnet.resolve_site_uuid", return_value=site_uuid),
        patch("open_fdd.platform.api.bacnet.store_bacnet_scan_ttl"),
        patch("open_fdd.platform.api.bacnet.sync_ttl_to_file"),
    ):
        r = client.post(
            "/bacnet/discovery-to-rdf",
            json={
                "request": {"start_instance": 3456789, "end_instance": 3456789},
                "import_into_data_model": True,
                "site_id": str(site_uuid),
                "create_site": False,
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert "import_result" in data
    imp = data["import_result"]
    assert imp["status"] == "imported"
    assert imp["points_created"] == 2
    assert imp["site_id"] == str(site_uuid)
