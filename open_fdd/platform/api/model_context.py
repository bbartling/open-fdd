"""
Model-context endpoints for external LLM tooling.

This module intentionally does *not* call any LLM provider.
It only serves Open-FDD documentation (and optionally a keyword-retrieved subset)
as plain text so an external agent can use it as context.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/model-context", tags=["model-context"])

DEFAULT_EXCERPT_MAX_CHARS = 28_000
DEFAULT_TOP_K = 6


@lru_cache(maxsize=1)
def _resolve_docs_path() -> Path | None:
    env_path = os.environ.get("OFDD_DOCS_PATH")
    if env_path:
        p = Path(env_path)
        return p if p.is_file() else None

    # Repo-root probing keeps dev and container layouts working.
    for base in [Path.cwd(), Path(__file__).resolve().parents[3]]:
        candidate = base / "pdf" / "open-fdd-docs.txt"
        if candidate.is_file():
            return candidate
    return None


def _load_docs_text() -> str:
    path = _resolve_docs_path()
    if not path:
        raise FileNotFoundError("Could not find pdf/open-fdd-docs.txt (or OFDD_DOCS_PATH)")
    return path.read_text(encoding="utf-8", errors="replace")


def _docs_excerpt(full: str, *, max_chars: int) -> str:
    if len(full) <= max_chars:
        return full.strip()
    return (full[:max_chars].rstrip() + "\n\n[... documentation truncated ...]").strip()


def _iter_chunks_by_top_heading(full: str) -> list[tuple[str, str]]:
    """
    Split the docs into chunks by top-level markdown headings (lines starting with '# ').

    build_docs_pdf.py builds a single top-level heading per page to keep TOC clean.
    """
    # Matches a page heading like: "# Getting Started"
    matches = list(re.finditer(r"(?m)^# (.+?)\s*$", full))
    if not matches:
        return []

    chunks: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full)
        title = m.group(1).strip()
        chunk_text = full[start:end].strip()
        chunks.append((title, chunk_text))
    return chunks


def _score_chunk(chunk_text: str, tokens: list[str]) -> int:
    t = chunk_text.lower()
    return sum(t.count(tok) for tok in tokens)


@router.get(
    "/docs",
    response_class=PlainTextResponse,
    summary="Open-FDD docs as plain model context",
    response_description="Text/plain documentation excerpt or retrieved subset.",
)
def get_docs_as_model_context(
    mode: str = Query(
        "excerpt",
        description="How to return docs: excerpt | full | slice. If 'query' is set, keyword retrieval overrides this.",
    ),
    max_chars: int = Query(
        DEFAULT_EXCERPT_MAX_CHARS,
        ge=1,
        le=2_000_000,
        description="Maximum characters to return. For 'excerpt'/'slice' this is the substring length; for retrieval it's the combined limit.",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Character offset used with mode='slice'.",
    ),
    query: str | None = Query(
        None,
        description="Optional keyword query. When set, this endpoint returns the most relevant doc sections (simple lexical matching; no embeddings).",
    ),
    top_k: int = Query(
        DEFAULT_TOP_K,
        ge=1,
        le=20,
        description="When query is set, how many sections to consider before truncation to max_chars.",
    ),
):
    try:
        full = _load_docs_text()
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None

    if query and query.strip():
        q = query.strip().lower()
        # Keep it lexical: tokens are alnum/'_'/'-' so it's stable for headings and endpoint names.
        raw_tokens = re.findall(r"[a-z0-9_-]{2,}", q)
        tokens = list(dict.fromkeys(raw_tokens))[:60]
        if not tokens:
            return PlainTextResponse(content=_docs_excerpt(full, max_chars=max_chars), media_type="text/plain")

        chunks = _iter_chunks_by_top_heading(full)
        if not chunks:
            return PlainTextResponse(content=_docs_excerpt(full, max_chars=max_chars), media_type="text/plain")

        scored: list[tuple[int, str, str]] = []
        for title, chunk_text in chunks:
            score = _score_chunk(chunk_text, tokens)
            if score > 0:
                scored.append((score, title, chunk_text))

        scored.sort(key=lambda x: (-x[0], x[1]))
        picked = scored[:top_k] if scored else []

        if not picked:
            return PlainTextResponse(content=_docs_excerpt(full, max_chars=max_chars), media_type="text/plain")

        out_parts: list[str] = []
        used = 0
        for _score, title, chunk_text in picked:
            # chunk_text already includes the page heading (starts with "# {title}").
            part = chunk_text
            if used + len(part) > max_chars:
                remaining = max_chars - used
                if remaining <= 0:
                    break
                out_parts.append(part[:remaining].rstrip())
                used = max_chars
                break
            out_parts.append(part)
            used += len(part)

        combined = "\n\n---\n\n".join(out_parts).strip()
        if len(combined) >= max_chars:
            combined = combined.rstrip() + "\n\n[... retrieved context truncated ...]"
        return PlainTextResponse(content=combined, media_type="text/plain")

    if mode == "full":
        return PlainTextResponse(content=full.strip(), media_type="text/plain")
    if mode == "excerpt":
        return PlainTextResponse(content=_docs_excerpt(full, max_chars=max_chars), media_type="text/plain")
    if mode == "slice":
        if offset >= len(full):
            return PlainTextResponse(content="", media_type="text/plain")
        return PlainTextResponse(
            content=_docs_excerpt(full[offset:], max_chars=max_chars),
            media_type="text/plain",
        )

    raise HTTPException(400, "Invalid mode. Expected: excerpt | full | slice")

