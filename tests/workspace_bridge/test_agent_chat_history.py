from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.agent_chat_history import (  # noqa: E402
    build_ollama_messages,
    normalize_history,
    trim_history,
)


def test_normalize_history_skips_pending_like_rows():
    raw = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "…"},
        {"role": "assistant", "content": "ok"},
        {"role": "system", "content": "ignored"},
    ]
    assert normalize_history(raw) == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
    ]


def test_trim_history_keeps_newest_within_char_budget():
    turns = [
        {"role": "user", "content": "old message one two three"},
        {"role": "assistant", "content": "old reply"},
        {"role": "user", "content": "new"},
        {"role": "assistant", "content": "yes"},
    ]
    trimmed = trim_history(turns, max_chars=30, max_turns=10)
    assert trimmed[-1]["content"] == "yes"
    assert all(t["content"] != "old message one two three" for t in trimmed)
    assert len(trimmed) < len(turns)


def test_build_ollama_messages_includes_system_history_and_user():
    msgs = build_ollama_messages(
        message="latest question",
        history=[{"role": "user", "content": "prior"}],
        system="sys",
    )
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[-1] == {"role": "user", "content": "latest question"}
    assert any(m["content"] == "prior" for m in msgs)


def test_mcp_hints_when_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_MCP_ENABLED", "1")
    monkeypatch.setenv("OFDD_MCP_REST_BASE", "http://127.0.0.1:8090")
    from openfdd_bridge.ollama_client import build_system_prompt, mcp_agent_hints

    hints = mcp_agent_hints()
    assert hints["mcp_enabled"] is True
    assert "8090" in hints["mcp_search_docs"]
    prompt = build_system_prompt()
    assert "search_docs" in prompt
