#!/usr/bin/env bash
# Build MCP RAG index from repo docs + bridge OpenAPI.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOCS="${ROOT}/docs"
OPENAPI="${ROOT}/workspace/api/static/openapi.json"
OUT="${ROOT}/workspace/data/mcp/rag_index.json"
BUILD="${ROOT}/skills/mcp-doc-retrieval/scripts/build_doc_index.py"

mkdir -p "$(dirname "$OUT")"
ARGS=(--docs-dir "$DOCS" --output "$OUT")
if [[ -f "$OPENAPI" ]]; then
  ARGS+=(--openapi-json "$OPENAPI")
fi
python3 "$BUILD" "${ARGS[@]}"
