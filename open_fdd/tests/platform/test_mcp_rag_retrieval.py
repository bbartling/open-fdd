from open_fdd.platform.mcp_rag.retrieval import RagIndex


def _sample_index() -> RagIndex:
    payload = {
        "docs": [
            {
                "chunk_id": "a",
                "source": "docs/operations/mcp_rag_service.md",
                "section": "MCP RAG service",
                "content": "Use bootstrap with --with-mcp-rag and search_docs tool.",
                "tags": ["docs", "markdown"],
                "endpoint_refs": ["/manifest"],
            },
            {
                "chunk_id": "b",
                "source": "openapi.json",
                "section": "openapi_paths",
                "content": "GET /data-model/export Export data model endpoint.",
                "tags": ["api", "openapi"],
                "endpoint_refs": ["/data-model/export"],
            },
        ],
        "idf": {"bootstrap": 2.0, "search_docs": 2.0, "/data-model/export": 2.0},
        "postings": {
            "bootstrap": {"a": 1},
            "search_docs": {"a": 1},
            "/data-model/export": {"b": 1},
        },
    }
    return RagIndex(payload)


def test_rag_index_search_returns_ranked_docs():
    idx = _sample_index()
    rows = idx.search("bootstrap search_docs", top_k=3)
    assert rows
    assert rows[0].chunk_id == "a"
    assert rows[0].source.endswith("mcp_rag_service.md")


def test_rag_index_search_filters_tags():
    idx = _sample_index()
    rows = idx.search("/data-model/export", top_k=3, tags=["api"])
    assert len(rows) == 1
    assert rows[0].chunk_id == "b"


def test_rag_index_get_section_by_source():
    idx = _sample_index()
    row = idx.get_section("docs/operations/mcp_rag_service.md")
    assert row["source"] == "docs/operations/mcp_rag_service.md"
    assert "--with-mcp-rag" in row["content"]

