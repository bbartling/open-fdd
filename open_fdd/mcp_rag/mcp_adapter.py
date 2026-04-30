from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any

import requests

DEFAULT_REST_BASE = os.getenv("OFDD_MCP_RAG_REST_BASE", "http://127.0.0.1:8090").rstrip("/")
DEFAULT_TIMEOUT_SEC = 20.0


@dataclass(frozen=True)
class ToolDef:
    name: str
    route: str
    mode: str


class OpenFddMcpAdapter:
    """Thin stdio MCP adapter over the Open-FDD MCP-RAG REST surface."""

    def __init__(self, *, rest_base: str = DEFAULT_REST_BASE, timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> None:
        self.rest_base = rest_base.rstrip("/")
        self.timeout_sec = timeout_sec

    def list_tools(self) -> list[ToolDef]:
        data = self._request_json("GET", "/manifest")
        out: list[ToolDef] = []
        for item in data.get("tools", []):
            out.append(
                ToolDef(
                    name=str(item.get("name", "")),
                    route=str(item.get("route", "")),
                    mode=str(item.get("mode", "")),
                )
            )
        return out

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request_json("POST", f"/tools/{name}", body=arguments or {})

    def _request_json(self, method: str, path: str, *, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.rest_base}{path}"
        try:
            resp = requests.request(
                method.upper(),
                url,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                json=body if body is not None else None,
                timeout=self.timeout_sec,
            )
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"MCP adapter upstream request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise RuntimeError(f"MCP adapter upstream HTTP {resp.status_code}: {resp.text}")
        if not (resp.text or "").strip():
            return {"ok": True}
        try:
            return resp.json()
        except ValueError:
            return {"ok": True, "text": resp.text}


def handle_jsonrpc_request(req: dict[str, Any], adapter: OpenFddMcpAdapter) -> dict[str, Any] | None:
    req_id = req.get("id")
    method = str(req.get("method") or "")
    params = req.get("params") or {}
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "open-fdd-mcp-adapter", "version": "0.1.0"},
                "capabilities": {"tools": {"listChanged": False}},
            },
        }
    if method == "tools/list":
        tools = adapter.list_tools()
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": t.name,
                        "description": f"Open-FDD tool ({t.mode})",
                        "inputSchema": {"type": "object", "additionalProperties": True},
                    }
                    for t in tools
                ]
            },
        }
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not name:
            return _jsonrpc_error(req_id, -32602, "Missing tools/call params.name")
        result = adapter.call_tool(name, arguments if isinstance(arguments, dict) else {})
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=True)}]},
        }
    return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")


def _jsonrpc_error(req_id: object, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def run_mcp_adapter() -> None:
    adapter = OpenFddMcpAdapter()
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                out = _jsonrpc_error(None, -32600, "Invalid Request")
            else:
                out = handle_jsonrpc_request(req, adapter)
        except json.JSONDecodeError:
            out = _jsonrpc_error(None, -32700, "Parse error")
        except Exception as exc:  # pragma: no cover
            out = _jsonrpc_error(None, -32000, str(exc))
        if out is not None:
            sys.stdout.write(json.dumps(out, ensure_ascii=True) + "\n")
            sys.stdout.flush()

