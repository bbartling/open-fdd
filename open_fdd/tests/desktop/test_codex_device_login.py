"""Unit tests for Codex device login helper (mocked HTTP)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from open_fdd.gateway import codex_device_login as m


@pytest.fixture(autouse=True)
def clear_sessions():
    with m._lock:
        m._sessions.clear()
    yield
    with m._lock:
        m._sessions.clear()


def test_start_device_login_parses_response():
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.text = '{"device_auth_id":"da1","user_code":"ABCD-EFGH","interval":5}'
    mock_resp.status_code = 200

    with patch("open_fdd.gateway.codex_device_login.requests.post", return_value=mock_resp) as post:
        out = m.start_device_login()
    assert "session_id" in out
    assert out["user_code"] == "ABCD-EFGH"
    assert out["verification_url"].endswith("/codex/device")
    post.assert_called_once()


def test_poll_pending_on_403():
    mock_start = MagicMock()
    mock_start.ok = True
    mock_start.text = '{"device_auth_id":"da1","user_code":"XY","interval":1}'
    mock_start.status_code = 200

    mock_poll = MagicMock()
    mock_poll.ok = False
    mock_poll.status_code = 403
    mock_poll.text = "{}"

    with patch("open_fdd.gateway.codex_device_login.requests.post", side_effect=[mock_start, mock_poll]):
        start = m.start_device_login()
        poll = m.poll_device_login(start["session_id"])
    assert poll["status"] == "pending"


def test_poll_complete_exchanges_token():
    mock_start = MagicMock()
    mock_start.ok = True
    mock_start.text = '{"device_auth_id":"da1","user_code":"XY","interval":1}'
    mock_start.status_code = 200

    mock_poll = MagicMock()
    mock_poll.ok = True
    mock_poll.text = '{"authorization_code":"ac","code_verifier":"cv"}'
    mock_poll.status_code = 200

    mock_oauth = MagicMock()
    mock_oauth.ok = True
    mock_oauth.text = '{"access_token":"atok","refresh_token":"rtok","expires_in":3600}'
    mock_oauth.status_code = 200

    with patch("open_fdd.gateway.codex_device_login.requests.post", side_effect=[mock_start, mock_poll, mock_oauth]):
        with patch.object(m.local_codex_cli, "persist_chatgpt_auth_from_device_tokens", return_value={"ok": True}):
            start = m.start_device_login()
            poll = m.poll_device_login(start["session_id"])
    assert poll["status"] == "complete"
    assert poll.get("codex_auth_persisted") is True
    assert "access_token" not in poll
    assert "refresh_token" not in poll
