#!/usr/bin/env python3
"""Rewrite Jekyll {% link path.md %} tags to use relative_url (GitHub Pages baseurl)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
LINK_RE = re.compile(r"\{%\s*link\s+([^%]+?)\s*%\}")


def md_path_to_site_path(md_path: str) -> str:
    path = md_path.strip().replace("\\", "/")
    if path.endswith("/index.md"):
        path = path[: -len("index.md")].rstrip("/")
        return f"/{path}/" if path else "/"
    if path.endswith(".md"):
        return f"/{path[:-3]}/"
    return f"/{path}/"


def rewrite(text: str) -> tuple[str, int]:
    count = 0

    def _repl(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        site_path = md_path_to_site_path(match.group(1))
        return f'{{{{ "{site_path}" | relative_url }}}}'

    return LINK_RE.sub(_repl, text), count


def main() -> int:
    total = 0
    for path in sorted(DOCS.rglob("*.md")):
        if "_site" in path.parts:
            continue
        original = path.read_text(encoding="utf-8")
        updated, n = rewrite(original)
        if n:
            path.write_text(updated, encoding="utf-8")
            total += n
            print(f"{path.relative_to(REPO)}: {n} link(s)")
    print(f"Rewrote {total} link tag(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
