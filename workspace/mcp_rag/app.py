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


class SearchApiRequest(BaseModel):
    query: str
    top_k: int = Field(default=8, ge=1, le=25)


_OPENAPI_CACHE: dict[str, Any] | None = None

FASTMCP_TOOLS = [
    "health_check",
    "portfolio_rollup",
    "building_agent_checkin",
    "get_tuning_brief",
    "preview_fdd_tuning",
    "apply_fdd_tuning",
    "list_fault_catalog",
    "get_fdd_results",
    "run_fdd_batch",
    "search_model",
    "get_equipment_context",
    "recommend_rules_for_equipment",
    "search_rule_cookbook",
    "draft_arrow_rule",
    "lint_rule",
    "save_rule",
    "bacnet_override_status",
    "search_docs",
    "get_doc_section",
    "commission_building_fdd",
    "diagnose_fault_trend",
    "tune_fdd_thresholds",
    "portfolio_morning_check",
    "write_rule_from_cookbook",
]


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
    idx_meta: dict[str, Any] = {"index_exists": INDEX_PATH.is_file()}
    if INDEX_PATH.is_file():
        try:
            idx = _load_index()
            idx_meta["chunk_count"] = len(idx.docs)
            idx_meta["doc_count"] = getattr(idx, "doc_count", None)
        except HTTPException:
            pass
    return {
        "name": "open-fdd-mcp",
        "version": "2.0.0",
        "mcp_transport": "/mcp (streamable-http)",
        "agent_note": (
            "Production CPU edges: use Cursor/Codex/OpenClaw MCP on /mcp — local Ollama is optional (GPU) or dev-only. "
            "Bridge agent tools: GET /openfdd-agent/context and POST /openfdd-agent/tool."
        ),
        "legacy_rest_tools": [
            {"name": "search_docs", "route": "POST /tools/search_docs"},
            {"name": "get_doc_section", "route": "POST /tools/get_doc_section"},
            {"name": "search_api_capabilities", "route": "POST /tools/search_api_capabilities"},
        ],
        "fastmcp_tools": FASTMCP_TOOLS,
        "fastmcp_tool_count": len(FASTMCP_TOOLS),
        "rag_index": idx_meta,
        "note": "Prefer MCP clients on /mcp; REST /tools/* for bridge-compat and lightweight doc search.",
    }


def _load_openapi_paths() -> list[dict[str, str]]:
    global _OPENAPI_CACHE
    if _OPENAPI_CACHE is not None:
        return _OPENAPI_CACHE.get("rows") or []

    import httpx

    base = os.getenv("OPENFDD_BRIDGE_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
    rows: list[dict[str, str]] = []
    try:
        with httpx.Client(timeout=4.0) as client:
            resp = client.get(f"{base}/openapi.json")
            resp.raise_for_status()
            spec = resp.json()
        for path, methods in (spec.get("paths") or {}).items():
            if not isinstance(methods, dict):
                continue
            for method, meta in methods.items():
                if method.startswith("x-") or not isinstance(meta, dict):
                    continue
                summary = str(meta.get("summary") or meta.get("description") or "").strip()
                rows.append(
                    {
                        "path": str(path),
                        "method": method.upper(),
                        "summary": summary[:240],
                        "haystack": f"{path} {method} {summary}".lower(),
                    }
                )
    except Exception:
        rows = []
    _OPENAPI_CACHE = {"rows": rows}
    return rows


@app.post("/tools/search_api_capabilities")
def search_api_capabilities(req: SearchApiRequest) -> dict[str, Any]:
    """Search bridge OpenAPI paths — helps external agents find REST routes."""
    q = req.query.strip().lower()
    if not q:
        raise HTTPException(status_code=400, detail="query required")
    tokens = [t for t in q.replace("/", " ").split() if t]
    rows = _load_openapi_paths()
    scored: list[tuple[float, dict[str, str]]] = []
    for row in rows:
        hay = row.get("haystack") or ""
        score = sum(1.0 for t in tokens if t in hay)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda x: (-x[0], x[1]["path"]))
    hits = [
        {"path": r["path"], "method": r["method"], "summary": r["summary"], "score": s}
        for s, r in scored[: req.top_k]
    ]
    return {"query": req.query, "count": len(hits), "results": hits, "openapi_source": "bridge"}


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
