from __future__ import annotations

from typing import Any

try:
    from open_fdd.mcp_rag.app import app as app
except ImportError:  # pragma: no cover - exercised in minimal installs
    app = None


def run_mcp_rag(host: str | None = None, port: int | None = None) -> None:
    """Lazy import FastAPI/uvicorn path only when actually running MCP RAG."""
    from open_fdd.mcp_rag.app import run_mcp_rag as _run_mcp_rag

    _run_mcp_rag(host=host, port=port)


def run_mcp_adapter() -> None:
    from open_fdd.mcp_rag.mcp_adapter import run_mcp_adapter as _run_mcp_adapter

    _run_mcp_adapter()


__all__ = ["app", "run_mcp_rag", "run_mcp_adapter"]

