"""Optional MCP RAG doc search sidecar (:8090)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .retrieval import RagIndex

INDEX_PATH = Path(
    os.getenv(
        "OFDD_MCP_RAG_INDEX_PATH",
        str(Path(__file__).resolve().parents[1] / "data" / "mcp" / "rag_index.json"),
    )
)

app = FastAPI(title="Open-FDD MCP RAG", version="1.0.0")
_idx: RagIndex | None = None


class SearchDocsRequest(BaseModel):
    query: str
    top_k: int = Field(default=6, ge=1, le=25)
    tags: list[str] | None = None


class GetSectionRequest(BaseModel):
    path_or_id: str


def _load_index() -> RagIndex:
    global _idx
    if _idx is None:
        if not INDEX_PATH.is_file():
            raise HTTPException(status_code=503, detail=f"RAG index missing: {INDEX_PATH}")
        _idx = RagIndex.from_path(INDEX_PATH)
    return _idx


def _serialize_results(query: str, rows: list[Any]) -> dict[str, Any]:
    return {
        "query": query,
        "count": len(rows),
        "results": [
            {
                "chunk_id": r.chunk_id,
                "score": round(r.score, 5),
                "source": r.source,
                "section": r.section,
                "content": r.content,
                "endpoint_refs": r.endpoint_refs,
                "tags": r.tags,
            }
            for r in rows
        ],
    }


@app.get("/health", response_model=None)
def health() -> dict[str, Any] | JSONResponse:
    body: dict[str, Any] = {"index_exists": INDEX_PATH.is_file(), "index_path": str(INDEX_PATH)}
    try:
        _load_index()
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"ok": False, **body, "error": detail})
    return {"ok": True, **body}


@app.get("/manifest")
def manifest() -> dict[str, Any]:
    return {
        "name": "open-fdd-mcp",
        "version": "2.0.0",
        "mcp_transport": "/mcp (streamable-http)",
        "tools": [
            {"name": "search_docs", "route": "/tools/search_docs", "legacy": True},
            {"name": "get_doc_section", "route": "/tools/get_doc_section", "legacy": True},
        ],
        "note": "Prefer MCP clients on /mcp; REST /tools/* kept for bridge compatibility.",
    }


@app.post("/tools/search_docs")
def search_docs(req: SearchDocsRequest) -> dict[str, Any]:
    idx = _load_index()
    rows = idx.search(req.query, top_k=req.top_k, tags=req.tags)
    return _serialize_results(req.query, rows)


@app.post("/tools/get_doc_section")
def get_doc_section(req: GetSectionRequest) -> dict[str, Any]:
    idx = _load_index()
    data = idx.get_section(req.path_or_id)
    if not data:
        raise HTTPException(status_code=404, detail="Section not found.")
    return data
