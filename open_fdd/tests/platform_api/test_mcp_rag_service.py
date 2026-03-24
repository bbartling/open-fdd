from pathlib import Path

from fastapi.testclient import TestClient

from open_fdd.platform.mcp_rag import app as mcp_app


def _write_index(tmp_path: Path) -> Path:
    p = tmp_path / "rag_index.json"
    p.write_text(
        """
{
  "version": 1,
  "doc_count": 1,
  "docs": [
    {
      "chunk_id": "chunk-1",
      "source": "docs/operations/mcp_rag_service.md",
      "section": "MCP RAG service",
      "content": "bootstrap with --with-mcp-rag and call search_docs",
      "tags": ["docs", "markdown"],
      "endpoint_refs": ["/manifest"],
      "length": 8
    }
  ],
  "idf": {"bootstrap": 2.0, "search_docs": 2.0},
  "postings": {"bootstrap": {"chunk-1": 1}, "search_docs": {"chunk-1": 1}}
}
""".strip(),
        encoding="utf-8",
    )
    return p


def test_manifest_includes_core_tools():
    client = TestClient(mcp_app.app)
    res = client.get("/manifest")
    assert res.status_code == 200
    tools = {t["name"] for t in res.json()["tools"]}
    assert "search_docs" in tools
    assert "get_doc_section" in tools
    assert "search_api_capabilities" in tools


def test_search_docs_reads_index(tmp_path: Path, monkeypatch):
    idx_path = _write_index(tmp_path)
    monkeypatch.setattr(mcp_app, "INDEX_PATH", idx_path)
    monkeypatch.setattr(mcp_app, "_idx", None)
    client = TestClient(mcp_app.app)

    res = client.post("/tools/search_docs", json={"query": "bootstrap", "top_k": 3})
    assert res.status_code == 200
    data = res.json()
    assert data["count"] >= 1
    assert data["results"][0]["chunk_id"] == "chunk-1"


def test_action_tool_blocked_when_disabled():
    client = TestClient(mcp_app.app)
    res = client.post("/tools/export_data_model")
    assert res.status_code == 403
    assert "disabled" in res.json()["detail"].lower()

