"""GPU gate for Agent chat and building insight Ollama calls."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_interactive_chat_disabled_without_gpu(monkeypatch: pytest.MonkeyPatch):
    from openfdd_bridge import ollama_client

    monkeypatch.setattr(ollama_client, "gpu_available", lambda: False)
    monkeypatch.setattr(ollama_client, "health", lambda timeout=None, max_total_s=None: {"ok": True})
    assert ollama_client.interactive_chat_enabled() is False


def test_interactive_chat_enabled_with_gpu(monkeypatch: pytest.MonkeyPatch):
    from openfdd_bridge import ollama_client

    monkeypatch.setattr(ollama_client, "gpu_available", lambda: True)
    monkeypatch.setattr(ollama_client, "health", lambda timeout=None, max_total_s=None: {"ok": True})
    assert ollama_client.interactive_chat_enabled() is True


def test_insight_skips_ollama_without_gpu(monkeypatch: pytest.MonkeyPatch):
    from openfdd_bridge import ollama_client

    monkeypatch.setattr(ollama_client, "gpu_available", lambda: False)
    monkeypatch.setattr(ollama_client, "health", lambda timeout=None, max_total_s=None: {"ok": True})
    assert ollama_client.should_use_ollama_for_insight() is False


def test_agent_chat_returns_disabled_without_gpu(monkeypatch: pytest.MonkeyPatch):
    from openfdd_bridge.routes import agent_routes

    monkeypatch.setattr(agent_routes.ollama_client, "interactive_chat_enabled", lambda: False)
    monkeypatch.setattr(agent_routes.ollama_client, "gpu_available", lambda: False)
    body = agent_routes.ChatBody(message="hello")
    out = agent_routes.agent_chat(body, _user={"role": "operator"})
    assert out["ok"] is False
    assert out["mode"] == "disabled"
