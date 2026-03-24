from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .retrieval import RagIndex


INDEX_PATH = Path(os.getenv("OFDD_MCP_RAG_INDEX_PATH", "/app/stack/mcp-rag/index/rag_index.json"))
OFDD_API_URL = os.getenv("OFDD_MCP_OFDD_API_URL", "http://api:8000").rstrip("/")
OFDD_API_KEY = os.getenv("OFDD_MCP_OFDD_API_KEY", "")
ENABLE_ACTION_TOOLS = os.getenv("OFDD_MCP_ENABLE_ACTION_TOOLS", "false").lower() == "true"
TIMEOUT = float(os.getenv("OFDD_MCP_HTTP_TIMEOUT_SEC", "20"))

app = FastAPI(title="Open-FDD MCP RAG Service", version="1.0.0")
_idx: RagIndex | None = None


class SearchDocsRequest(BaseModel):
    query: str
    top_k: int = Field(default=6, ge=1, le=25)
    tags: list[str] | None = None


class GetSectionRequest(BaseModel):
    path_or_id: str


class PlaybookRequest(BaseModel):
    task_type: str


class ImportRequest(BaseModel):
    payload: dict[str, Any]


class SparqlRequest(BaseModel):
    query: str


def _load_index() -> RagIndex:
    global _idx
    if _idx is None:
        if not INDEX_PATH.exists():
            raise HTTPException(status_code=503, detail=f"RAG index missing: {INDEX_PATH}")
        _idx = RagIndex.from_path(INDEX_PATH)
    return _idx


def _headers() -> dict[str, str]:
    h = {"Accept": "application/json"}
    if OFDD_API_KEY:
        h["Authorization"] = f"Bearer {OFDD_API_KEY}"
    return h


def _require_action_tools() -> None:
    if not ENABLE_ACTION_TOOLS:
        raise HTTPException(status_code=403, detail="Action tools disabled.")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "index_exists": INDEX_PATH.exists(),
        "index_path": str(INDEX_PATH),
        "action_tools_enabled": ENABLE_ACTION_TOOLS,
    }


@app.get("/manifest")
def manifest() -> dict[str, Any]:
    return {
        "name": "open-fdd-mcp-rag",
        "version": "1.0.0",
        "tools": [
            {"name": "search_docs", "route": "/tools/search_docs", "mode": "read"},
            {"name": "get_doc_section", "route": "/tools/get_doc_section", "mode": "read"},
            {"name": "search_api_capabilities", "route": "/tools/search_api_capabilities", "mode": "read"},
            {"name": "get_operator_playbook", "route": "/tools/get_operator_playbook", "mode": "read"},
            {"name": "export_data_model", "route": "/tools/export_data_model", "mode": "write_guarded"},
            {"name": "import_data_model", "route": "/tools/import_data_model", "mode": "write_guarded"},
            {"name": "rules_sync_definitions", "route": "/tools/rules_sync_definitions", "mode": "write_guarded"},
            {"name": "sparql_validate", "route": "/tools/sparql_validate", "mode": "write_guarded"},
        ],
    }


@app.post("/tools/search_docs")
def search_docs(req: SearchDocsRequest) -> dict[str, Any]:
    idx = _load_index()
    rows = idx.search(req.query, top_k=req.top_k, tags=req.tags)
    return {
        "query": req.query,
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


@app.post("/tools/get_doc_section")
def get_doc_section(req: GetSectionRequest) -> dict[str, Any]:
    idx = _load_index()
    data = idx.get_section(req.path_or_id)
    if not data:
        raise HTTPException(status_code=404, detail="Section not found.")
    return data


@app.post("/tools/search_api_capabilities")
def search_api_capabilities(req: SearchDocsRequest) -> dict[str, Any]:
    idx = _load_index()
    rows = idx.search(req.query, top_k=req.top_k, tags=["api"])
    return {
        "query": req.query,
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


@app.post("/tools/get_operator_playbook")
def get_operator_playbook(req: PlaybookRequest) -> dict[str, Any]:
    idx = _load_index()
    prompt = f"operator playbook {req.task_type} integrity sweep overnight review"
    rows = idx.search(prompt, top_k=8, tags=["docs", "markdown"])
    return {
        "task_type": req.task_type,
        "playbook": [r.content for r in rows],
        "sources": sorted({r.source for r in rows}),
    }


@app.post("/tools/export_data_model")
def export_data_model() -> dict[str, Any]:
    _require_action_tools()
    resp = requests.get(f"{OFDD_API_URL}/data-model/export", headers=_headers(), timeout=TIMEOUT)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


@app.post("/tools/import_data_model")
def import_data_model(req: ImportRequest) -> dict[str, Any]:
    _require_action_tools()
    resp = requests.put(
        f"{OFDD_API_URL}/data-model/import",
        headers={**_headers(), "Content-Type": "application/json"},
        json=req.payload,
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json() if resp.text else {"ok": True}


@app.post("/tools/rules_sync_definitions")
def rules_sync_definitions() -> dict[str, Any]:
    _require_action_tools()
    resp = requests.post(
        f"{OFDD_API_URL}/rules/sync-definitions",
        headers={**_headers(), "Content-Type": "application/json"},
        json={},
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json() if resp.text else {"ok": True}


@app.post("/tools/sparql_validate")
def sparql_validate(req: SparqlRequest) -> dict[str, Any]:
    _require_action_tools()
    resp = requests.post(
        f"{OFDD_API_URL}/data-model/sparql",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"query": req.query},
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()

