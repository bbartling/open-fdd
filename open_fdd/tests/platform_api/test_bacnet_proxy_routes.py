"""BACnet proxy POST routes: JSON-RPC shape forwarded to gateway (httpx mocked)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app

client = TestClient(app)


def _mock_httpx_ok(json_body: dict):
    m = MagicMock()
    m.is_success = True
    m.status_code = 200
    m.json.return_value = json_body
    m.text = ""
    return m


@patch("open_fdd.platform.api.bacnet.httpx.post")
def test_bacnet_read_property_proxy(mock_post, monkeypatch):
    monkeypatch.setenv("OFDD_BACNET_SERVER_API_KEY", "test-bacnet-proxy-key")
    mock_post.return_value = _mock_httpx_ok(
        {"jsonrpc": "2.0", "id": "0", "result": {"present-value": 42}}
    )
    r = client.post(
        "/bacnet/read_property",
        json={
            "request": {
                "device_instance": 123,
                "object_identifier": "analog-input,1",
                "property_identifier": "present-value",
            }
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    mock_post.assert_called_once()
    call_kw = mock_post.call_args.kwargs
    assert call_kw["headers"].get("Authorization") == "Bearer test-bacnet-proxy-key"
    assert call_kw["json"]["method"] == "client_read_property"
    assert call_kw["json"]["params"] == {
        "request": {
            "device_instance": 123,
            "object_identifier": "analog-input,1",
            "property_identifier": "present-value",
        }
    }


def test_bacnet_read_property_rejects_non_allowlisted_url():
    """Caller-supplied gateway URL must match configured gateways (no bearer exfiltration)."""
    r = client.post(
        "/bacnet/read_property",
        json={
            "url": "https://evil.example.com",
            "request": {
                "device_instance": 1,
                "object_identifier": "analog-input,1",
                "property_identifier": "present-value",
            },
        },
    )
    assert r.status_code == 403


@patch("open_fdd.platform.api.bacnet.httpx.post")
def test_bacnet_write_property_proxy(mock_post):
    mock_post.return_value = _mock_httpx_ok({"jsonrpc": "2.0", "id": "0", "result": {}})
    r = client.post(
        "/bacnet/write_property",
        json={
            "request": {
                "device_instance": 9,
                "object_identifier": "analog-output,2",
                "property_identifier": "present-value",
                "value": None,
                "priority": 8,
            }
        },
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True
    params = mock_post.call_args.kwargs["json"]["params"]
    assert params["request"]["value"] is None
    assert params["request"]["priority"] == 8


def test_bacnet_write_property_missing_priority_422():
    """Open-FDD proxy always requires priority 1–16 (avoids ambiguous BACnet writes)."""
    r = client.post(
        "/bacnet/write_property",
        json={
            "request": {
                "device_instance": 9,
                "object_identifier": "analog-output,2",
                "property_identifier": "present-value",
                "value": 72.0,
            }
        },
    )
    assert r.status_code == 422


@patch("open_fdd.platform.api.bacnet.httpx.post")
def test_bacnet_supervisory_proxy(mock_post):
    mock_post.return_value = _mock_httpx_ok(
        {"jsonrpc": "2.0", "id": "0", "result": {"device_id": 1, "points": [], "summary": {}}}
    )
    r = client.post(
        "/bacnet/supervisory_logic_checks",
        json={"instance": {"device_instance": 555}},
    )
    assert r.status_code == 200
    assert mock_post.call_args.kwargs["json"]["params"] == {
        "instance": {"device_instance": 555}
    }


@patch("open_fdd.platform.api.bacnet.httpx.post")
def test_bacnet_read_multiple_proxy(mock_post):
    mock_post.return_value = _mock_httpx_ok(
        {
            "jsonrpc": "2.0",
            "id": "0",
            "result": {"success": True, "message": "ok", "data": {"results": []}},
        }
    )
    r = client.post(
        "/bacnet/read_multiple",
        json={
            "request": {
                "device_instance": 7,
                "requests": [
                    {"object_identifier": "ai,1", "property_identifier": "present-value"}
                ],
            }
        },
    )
    assert r.status_code == 200
    assert mock_post.call_args.kwargs["json"]["method"] == "client_read_multiple"


@patch("open_fdd.platform.api.bacnet.httpx.post")
def test_bacnet_read_point_priority_array_proxy(mock_post):
    mock_post.return_value = _mock_httpx_ok(
        {"jsonrpc": "2.0", "id": "0", "result": [None, 72.0]}
    )
    r = client.post(
        "/bacnet/read_point_priority_array",
        json={"request": {"device_instance": 1, "object_identifier": "analog-output,3"}},
    )
    assert r.status_code == 200
    assert mock_post.call_args.kwargs["json"]["method"] == "client_read_point_priority_array"
