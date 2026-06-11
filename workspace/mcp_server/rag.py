from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_rag.retrieval import RagIndex

from .errors import McpError


class DocSearch:
    def __init__(self, index_path: Path) -> None:
        self.index_path = index_path
        self._index: RagIndex | None = None

    def _load(self) -> RagIndex:
        if self._index is None:
            if not self.index_path.is_file():
                raise McpError(f"RAG index missing: {self.index_path}")
            self._index = RagIndex.from_path(self.index_path)
        return self._index

    def search(self, query: str, top_k: int = 6, tags: list[str] | None = None) -> dict[str, Any]:
        idx = self._load()
        rows = idx.search(query, top_k=top_k, tags=tags)
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

    def get_section(self, path_or_id: str) -> dict[str, Any]:
        idx = self._load()
        data = idx.get_section(path_or_id)
        if not data:
            raise McpError(f"doc section not found: {path_or_id}")
        return data

    def metadata(self) -> dict[str, Any]:
        return {
            "index_path": str(self.index_path),
            "index_exists": self.index_path.is_file(),
            "chunk_count": len(self._load().docs) if self.index_path.is_file() else 0,
        }
