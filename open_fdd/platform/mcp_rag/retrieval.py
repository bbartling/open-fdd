from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Any

TOKEN_RE = re.compile(r"[a-zA-Z0-9_./:-]{2,}")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text)]


@dataclass
class SearchResult:
    chunk_id: str
    score: float
    source: str
    section: str
    content: str
    endpoint_refs: list[str]
    tags: list[str]


class RagIndex:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.docs = payload.get("docs", [])
        self.idf = payload.get("idf", {})
        self.postings = payload.get("postings", {})
        self._doc_map = {d["chunk_id"]: d for d in self.docs}

    @classmethod
    def from_path(cls, path: Path) -> "RagIndex":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(payload)

    def search(self, query: str, top_k: int = 5, tags: list[str] | None = None) -> list[SearchResult]:
        q_tokens = tokenize(query)
        if not q_tokens:
            return []

        q_tf = Counter(q_tokens)
        q_vec = {}
        for t, tf in q_tf.items():
            q_vec[t] = tf * float(self.idf.get(t, 1.0))
        q_norm = sqrt(sum(v * v for v in q_vec.values())) or 1.0

        scores: dict[str, float] = {}
        d_norms: dict[str, float] = {}
        for t, q_w in q_vec.items():
            postings = self.postings.get(t, {})
            idf = float(self.idf.get(t, 1.0))
            for chunk_id, tf in postings.items():
                d_w = float(tf) * idf
                scores[chunk_id] = scores.get(chunk_id, 0.0) + (q_w * d_w)
                d_norms[chunk_id] = d_norms.get(chunk_id, 0.0) + (d_w * d_w)

        out: list[SearchResult] = []
        for chunk_id, dot in scores.items():
            doc = self._doc_map.get(chunk_id)
            if not doc:
                continue
            if tags:
                doc_tags = set(doc.get("tags", []))
                if not doc_tags.intersection(tags):
                    continue
            norm = sqrt(d_norms.get(chunk_id, 1.0)) * q_norm
            score = dot / (norm or 1.0)
            out.append(
                SearchResult(
                    chunk_id=chunk_id,
                    score=score,
                    source=doc.get("source", ""),
                    section=doc.get("section", ""),
                    content=doc.get("content", ""),
                    endpoint_refs=doc.get("endpoint_refs", []),
                    tags=doc.get("tags", []),
                )
            )
        out.sort(key=lambda x: x.score, reverse=True)
        return out[: max(1, min(top_k, 25))]

    def get_section(self, source_or_chunk: str) -> dict[str, Any]:
        if source_or_chunk in self._doc_map:
            return self._doc_map[source_or_chunk]
        candidates = [d for d in self.docs if d.get("source") == source_or_chunk]
        if not candidates:
            return {}
        combined = "\n\n".join(d.get("content", "") for d in candidates[:20])
        return {
            "source": source_or_chunk,
            "section": "combined",
            "content": combined,
            "tags": sorted({t for d in candidates for t in d.get("tags", [])}),
            "endpoint_refs": sorted({e for d in candidates for e in d.get("endpoint_refs", [])}),
        }

