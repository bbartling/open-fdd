"""CLI entry: stdio MCP or streamable HTTP (legacy REST on same port via asgi factory)."""

from __future__ import annotations

import os

from .config import McpConfig
from .server import mcp


def main() -> None:
    cfg = McpConfig.from_env()
    transport = cfg.transport
    if transport == "stdio":
        mcp.run(transport="stdio")
        return
    if transport in {"streamable-http", "http", "sse"}:
        import uvicorn

        uvicorn.run(
            "mcp_server.asgi:create_app",
            factory=True,
            host=cfg.host,
            port=cfg.port,
            log_level=os.getenv("OFDD_MCP_LOG_LEVEL", "info"),
        )
        return
    raise SystemExit(f"unsupported OFDD_MCP_TRANSPORT: {transport}")


if __name__ == "__main__":
    main()
