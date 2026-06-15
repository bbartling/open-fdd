#!/usr/bin/env python3
"""Build a lightweight doc/API RAG index for generated MCP services."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from math import log
from pathlib import Path
from typing import Any

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TOKEN_RE = re.compile(r"[a-zA-Z0-9_./:-]{2,}")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text)]


@dataclass
class Chunk:
    chunk_id: str
    source: str
    section: str
    content: str
    tags: list[str]
    endpoint_refs: list[str]


def extract_endpoints(text: str) -> list[str]:
    out = set()
    for token in TOKEN_RE.findall(text):
        if token.startswith("/"):
            out.add(token)
    return sorted(out)


def read_markdown_chunks(path: Path, chunk_size: int) -> list[Chunk]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    chunks: list[Chunk] = []
    current_section = path.stem
    buf: list[str] = []
    idx = 0
    section_idx = 0

    def flush() -> None:
        nonlocal idx, buf
        if not buf:
            return
        raw = "\n".join(buf).strip()
        buf = []
        if not raw:
            return
        words = raw.split()
        start = 0
        sub = 0
        while start < len(words):
            content = " ".join(words[start : start + chunk_size]).strip()
            if content:
                chunks.append(
                    Chunk(
                        chunk_id=f"{path.as_posix()}::{section_idx}:{sub}:{idx}",
                        source=path.as_posix(),
                        section=current_section,
                        content=content,
                        tags=["docs", "markdown"],
                        endpoint_refs=extract_endpoints(content),
                    )
                )
                idx += 1
            start += chunk_size
            sub += 1

    for line in lines:
        match = HEADING_RE.match(line)
        if match:
            flush()
            section_idx += 1
            current_section = match.group(2).strip()
            buf.append(line)
            continue
        buf.append(line)
    flush()
    return chunks


def read_openapi_chunks(path: Path) -> list[Chunk]:
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    chunks: list[Chunk] = []
    for endpoint, methods in (spec.get("paths", {}) if isinstance(spec, dict) else {}).items():
        if not isinstance(methods, dict):
            continue
        for method, data in methods.items():
            if not isinstance(data, dict):
                continue
            content = (
                f"{method.upper()} {endpoint}\n{data.get('summary', '')}\n"
                f"{data.get('description', '')}"
            ).strip()
            chunks.append(
                Chunk(
                    chunk_id=f"{path.as_posix()}::{method}:{endpoint}",
                    source=path.as_posix(),
                    section="openapi_paths",
                    content=content,
                    tags=["api", "openapi"],
                    endpoint_refs=[endpoint],
                )
            )
    return chunks


def build_index(chunks: list[Chunk]) -> dict[str, Any]:
    docs = []
    df: Counter[str] = Counter()
    postings: dict[str, dict[str, int]] = defaultdict(dict)
    tokenized: list[list[str]] = []
    for c in chunks:
        tokens = tokenize(c.content)
        tokenized.append(tokens)
        for token in set(tokens):
            df[token] += 1
    for idx, c in enumerate(chunks):
        tf = Counter(tokenized[idx])
        for token, count in tf.items():
            postings[token][c.chunk_id] = count
        docs.append(
            {
                "chunk_id": c.chunk_id,
                "source": c.source,
                "section": c.section,
                "content": c.content,
                "tags": c.tags,
                "endpoint_refs": c.endpoint_refs,
                "length": len(tokenized[idx]),
            }
        )
    total_docs = max(1, len(chunks))
    idf = {token: log((1 + total_docs) / (1 + dcount)) + 1.0 for token, dcount in df.items()}
    return {"version": 1, "doc_count": len(chunks), "docs": docs, "idf": idf, "postings": postings}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build MCP doc index JSON.")
    parser.add_argument("--docs-dir", type=Path, required=True)
    parser.add_argument("--openapi-json", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chunk-size", type=int, default=220)
    args = parser.parse_args()
    if int(args.chunk_size) <= 0:
        parser.error("--chunk-size must be > 0")
    chunks: list[Chunk] = []
    if args.docs_dir.is_dir():
        skip_parts = {"dev", "_site", "_build"}
        skip_names = {"docs_cleanup_plan.md", "DOCUMENTATION_CHECKLIST.md", "404.md"}
        for md in sorted(args.docs_dir.rglob("*.md")):
            if any(part in skip_parts for part in md.parts):
                continue
            if md.name in skip_names:
                continue
            if md.is_relative_to(args.docs_dir / "agent-skills"):
                continue
            chunks.extend(read_markdown_chunks(md, args.chunk_size))
    if args.openapi_json and args.openapi_json.exists():
        chunks.extend(read_openapi_chunks(args.openapi_json))
    if not chunks:
        raise SystemExit("No content found to index.")
    out = build_index(chunks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote RAG index: {args.output} ({out['doc_count']} chunks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
