from __future__ import annotations

import json
from typing import Any

from open_fdd.mcp_rag.mcp_adapter import OpenFddMcpAdapter, handle_jsonrpc_request


def test_handle_initialize_returns_capabilities() -> None:
    adapter = OpenFddMcpAdapter(rest_base="http://127.0.0.1:8090")
    out = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, adapter)
    assert out is not None
    assert out["id"] == 1
    assert out["result"]["serverInfo"]["name"] == "open-fdd-mcp-adapter"


def test_tools_list_maps_manifest(monkeypatch) -> None:
    adapter = OpenFddMcpAdapter(rest_base="http://127.0.0.1:8090")

    def _fake(method: str, path: str, *, body: dict[str, Any] | None = None) -> dict[str, Any]:  # noqa: ARG001
        assert method == "GET"
        assert path == "/manifest"
        return {"tools": [{"name": "search_docs", "route": "/tools/search_docs", "mode": "read"}]}

    monkeypatch.setattr(adapter, "_request_json", _fake)
    out = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, adapter)
    assert out is not None
    tools = out["result"]["tools"]
    assert tools[0]["name"] == "search_docs"


def test_tools_call_serializes_result(monkeypatch) -> None:
    adapter = OpenFddMcpAdapter(rest_base="http://127.0.0.1:8090")

    def _fake_call(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        assert name == "openclaw_cron_validate"
        assert arguments == {"expression": "0 */6 * * *"}
        return {"valid": True}

    monkeypatch.setattr(adapter, "call_tool", _fake_call)
    out = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "openclaw_cron_validate", "arguments": {"expression": "0 */6 * * *"}},
        },
        adapter,
    )
    assert out is not None
    text = out["result"]["content"][0]["text"]
    parsed = json.loads(text)
    assert parsed["valid"] is True
