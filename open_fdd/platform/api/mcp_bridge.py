"""
HTTP discovery manifest for MCP-style agent tooling.

Open-FDD does **not** ship an MCP stdio/SSE server inside the API process. This
module exposes a small JSON manifest so external clients (Cursor, custom agents,
or a separate MCP server you host) can discover stable URLs for documentation
context and common CRUD operations—without scraping OpenAPI by hand.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/mcp", tags=["mcp"])

SCHEMA_VERSION = "open-fdd-mcp-bridge/1"


@router.get(
    "/manifest",
    summary="MCP-style discovery manifest (resources + tool HTTP mappings)",
    response_description="JSON manifest for agent discovery.",
)
def get_mcp_manifest() -> dict:
    """
    Return a versioned manifest listing logical resources and tools with their
    HTTP equivalents. Invoke tools by performing the described HTTP requests
    (same auth as the rest of the API when OFDD_API_KEY is set).
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "server": {
            "name": "open-fdd",
            "summary": "Open-FDD — edge HVAC fault detection & Brick/BACnet data model",
        },
        "resources": [
            {
                "uri": "openfdd://docs",
                "name": "open_fdd_documentation",
                "mimeType": "text/plain",
                "description": (
                    "Bundled Open-FDD documentation as plain text "
                    "(built from docs/ into pdf/open-fdd-docs.txt)."
                ),
                "http": {"method": "GET", "path": "/model-context/docs"},
            }
        ],
        "tools": [
            {
                "name": "fetch_openfdd_docs",
                "description": (
                    "Load Open-FDD docs as plain text for LLM context. "
                    "Supports excerpt/full/slice and optional keyword retrieval via query=."
                ),
                "http": {"method": "GET", "path": "/model-context/docs"},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["excerpt", "full", "slice"],
                            "description": "Ignored when query= is set (retrieval mode).",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "Character budget (default ~28k for excerpt).",
                        },
                        "offset": {"type": "integer", "description": "For mode=slice."},
                        "query": {
                            "type": "string",
                            "description": "Keyword query; returns top matching doc sections.",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Max sections when query= is set (default 6).",
                        },
                    },
                },
            },
            {
                "name": "data_model_export",
                "description": "Export points (and equipment metadata) as JSON for external tagging.",
                "http": {"method": "GET", "path": "/data-model/export"},
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "data_model_import",
                "description": "Apply tagged points/equipment JSON (Brick fields, feeds/fed_by).",
                "http": {"method": "PUT", "path": "/data-model/import"},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "body": {
                            "type": "object",
                            "description": "Same shape as PUT /data-model/import (points array or wrapper).",
                        }
                    },
                    "required": ["body"],
                },
            },
            {
                "name": "capabilities",
                "description": "API version and feature flags (WebSocket, jobs, BACnet write, etc.).",
                "http": {"method": "GET", "path": "/capabilities"},
                "inputSchema": {"type": "object", "properties": {}},
            },
        ],
        "notes": [
            "Authentication: when OFDD_API_KEY is set, send Authorization: Bearer <key> like other routes.",
            "For integrating OpenAI-compatible stacks (e.g. external Open-Claw), see docs/openclaw_integration.md.",
            "This manifest is informational; it is not a full MCP JSON-RPC session.",
        ],
    }
