# MCP RAG — reference

Legacy: `open_fdd/mcp_rag/app.py`, `retrieval.py`, `mcp_adapter.py`.

Env: `OFDD_MCP_RAG_INDEX_PATH`, `OFDD_MCP_OFDD_API_URL`, `OFDD_MCP_OFDD_API_KEY`, `OFDD_MCP_ENABLE_ACTION_TOOLS`, `OFDD_MCP_LISTEN_HOST`, `OFDD_MCP_LISTEN_PORT`.

Read tools: `search_docs`, `search_api_capabilities`, `get_doc_section`.

Write/proxy tools (gated): bridge health, ingest, rules put, SPARQL, OpenClaw helpers.

Index builder retired from `scripts/build_mcp_rag_index.py`; use skill script.
