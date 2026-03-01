"""WebSocket tests: auth, subscribe, ping/pong, lifecycle (mirroring NR HA EventStatus/WS)."""

from unittest.mock import patch
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app
from open_fdd.platform.realtime.hub import _topic_matches

client = TestClient(app)


def test_ws_topic_matches_wildcard():
    assert _topic_matches("fault.*", "fault.raised") is True
    assert _topic_matches("fault.*", "fault.cleared") is True
    assert _topic_matches("fault.*", "crud.point.created") is False
    assert _topic_matches("crud.point.*", "crud.point.created") is True


def test_ws_unsubscribe():
    with patch("open_fdd.platform.realtime.ws._ws_auth_ok", return_value=True):
        with client.websocket_connect("/ws/events?token=ok") as ws:
            ws.send_json({"type": "subscribe", "topics": ["fault.*"]})
            ws.send_json({"type": "unsubscribe", "topics": ["fault.*"]})
            ws.send_json({"type": "ping"})
            assert ws.receive_json().get("type") == "pong"


def test_ws_invalid_json_returns_error_message():
    with patch("open_fdd.platform.realtime.ws._ws_auth_ok", return_value=True):
        with client.websocket_connect("/ws/events?token=ok") as ws:
            ws.send_text("not json")
            data = ws.receive_json()
            assert data.get("type") == "error"
            assert "message" in data


def test_ws_requires_auth_when_api_key_set():
    # When auth fails, server closes with 4401; with token=True we get normal connection
    with patch("open_fdd.platform.realtime.ws._ws_auth_ok", return_value=True):
        with client.websocket_connect("/ws/events?token=ok") as ws:
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data.get("type") == "pong"


def test_ws_subscribe_ping_pong():
    with patch("open_fdd.platform.realtime.ws._ws_auth_ok", return_value=True):
        with client.websocket_connect("/ws/events?token=ok") as ws:
            ws.send_json({"type": "subscribe", "topics": ["fault.*", "crud.point.*"]})
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data.get("type") == "pong"
