#!/usr/bin/env python3
"""Verify MCP/RAG and plain-text doc bundles include required agent phrases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

REQUIRED_PHRASES = (
    "apply_faults_arrow",
    "DataFusion SQL",
    "Fault confirmation",
    "commissioning-export",
    "commissioning-import",
    "fdd_input",
    "fdd_rule_ids",
    "BACnet",
    "Niagara baskStream",
    "JSON API",
    "Platform API profile",
    "ACME live validation",
    "Bench 5007",
    "no secrets",
)

EXCLUDED_STALE_MARKERS = (
    "pr-rust-prep-audit",
    "docs_cleanup_plan",
    "DOCUMENTATION_CHECKLIST",
)


def _bundle_text(path: Path) -> str:
    if not path.is_file():
        return ""
    if path.suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return ""
        parts: list[str] = []
        for doc in data.get("docs") or []:
            if isinstance(doc, dict):
                parts.append(str(doc.get("content") or ""))
                parts.append(str(doc.get("source") or ""))
        return "\n".join(parts)
    return path.read_text(encoding="utf-8", errors="replace")


def validate_bundle(text: str, *, label: str) -> tuple[list[str], list[str]]:
    missing = [p for p in REQUIRED_PHRASES if p not in text]
    stale = [m for m in EXCLUDED_STALE_MARKERS if m in text]
    return missing, stale


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate MCP/doc-search bundle phrases")
    parser.add_argument(
        "--text-bundle",
        type=Path,
        default=REPO / "pdf" / "open-fdd-docs.txt",
        help="Plain-text docs bundle (from build_docs_pdf.py)",
    )
    parser.add_argument(
        "--rag-index",
        type=Path,
        default=REPO / "workspace" / "data" / "mcp" / "rag_index.json",
        help="MCP RAG index JSON",
    )
    args = parser.parse_args()

    failures = 0
    for label, path in (("text-bundle", args.text_bundle), ("rag-index", args.rag_index)):
        text = _bundle_text(path)
        if not text:
            print(f"SKIP {label}: missing or empty ({path})", file=sys.stderr)
            continue
        missing, stale = validate_bundle(text, label=label)
        if missing:
            failures += 1
            print(f"FAIL {label}: missing phrases: {', '.join(missing)}", file=sys.stderr)
        else:
            print(f"OK {label}: all required phrases present ({path})")
        if stale:
            print(f"WARN {label}: stale markers indexed: {', '.join(stale)}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
