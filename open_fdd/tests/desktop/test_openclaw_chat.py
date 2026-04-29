"""Tests for OpenClaw gateway chat client (mocked HTTP)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from open_fdd.gateway.openclaw_chat import OpenClawGatewayChatClient


def test_complete_raises_without_token() -> None:
    client = OpenClawGatewayChatClient(gateway_token="")
    with pytest.raises(ValueError, match="Missing gateway token"):
        client.complete([{"role": "user", "content": "hi"}])


def test_complete_raises_on_empty_messages() -> None:
    client = OpenClawGatewayChatClient(gateway_token="secret")
    with pytest.raises(ValueError, match="non-empty"):
        client.complete([])


def test_complete_parses_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": "hello from codex path"}}],
        "id": "chatcmpl-test",
    }
    session.post.return_value = resp

    client = OpenClawGatewayChatClient(
        base_url="http://gw:18789",
        gateway_token="tok",
        backend_model="openai-codex/gpt-5.5",
        session=session,
    )
    out = client.complete([{"role": "user", "content": "ping"}], user="fdd-smoke")

    assert out.content == "hello from codex path"
    session.post.assert_called_once()
    call_kw = session.post.call_args
    assert call_kw[0][0] == "http://gw:18789/v1/chat/completions"
    headers = call_kw[1]["headers"]
    assert headers["Authorization"] == "Bearer tok"
    assert headers["x-openclaw-model"] == "openai-codex/gpt-5.5"
    body = __import__("json").loads(call_kw[1]["data"])
    assert body["model"] == "openclaw/default"
    assert body["messages"][0]["content"] == "ping"
    assert body["user"] == "fdd-smoke"


def test_complete_http_error() -> None:
    session = MagicMock()
    resp = MagicMock()
    resp.status_code = 401
    resp.text = "unauthorized"
    session.post.return_value = resp

    client = OpenClawGatewayChatClient(
        base_url="http://127.0.0.1:18789",
        gateway_token="bad",
        session=session,
    )
    with pytest.raises(RuntimeError, match="HTTP 401"):
        client.complete([{"role": "user", "content": "x"}])
