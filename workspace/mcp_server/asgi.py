"""Combined ASGI app: legacy REST (/health, /tools/*) + MCP streamable HTTP (/mcp)."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.routing import Mount

from mcp_rag.app import app as legacy_app

from .server import mcp


def create_app() -> Starlette:
    return Starlette(
        routes=[
            Mount("/mcp", app=mcp.streamable_http_app()),
            Mount("/", app=legacy_app),
        ]
    )
