#!/usr/bin/env python3
"""Find broken relative links in the repo's Markdown (README, docs, app READMEs).

    python3 scripts/check_links.py            # exit 1 on any broken link
    python3 scripts/check_links.py FILE...    # check just these files

Handles Markdown links/images and HTML src/href. In docs/, a link to `page.html` is accepted when
`page.md` exists (the Jekyll output). External (http, mailto) links and pure anchors are skipped.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DEFAULT = ["README.md", "SECURITY.md", "AGENTS.md", "CHANGELOG.md", "nf-app/README.md", "lite/README.md",
           "deploy/nf-caddy/README.md", "tools/rdf-check/README.md",
           "tools/bacnet-scan/README.md", "scripts/nf/README.md", "scripts/nf/tools/README.md"]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|(?:src|href)=\"([^\"]+)\"")
FENCE = re.compile(r"^(```|~~~)")


def is_generated_docs_file(path: Path) -> bool:
    """Exclude local Bundler/Jekyll output, which is neither project source nor link-check input."""
    try:
        parts = path.relative_to(DOCS).parts
    except ValueError:
        return False
    return parts[:2] == ("vendor", "bundle") or bool(parts and parts[0] == "_site")


def targets(path: Path):
    in_fence = False
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE.match(line.strip()):
            in_fence = not in_fence
        if in_fence:
            continue
        for m in LINK.finditer(re.sub(r"`[^`]*`", "", line)):
            yield n, m.group(1) or m.group(2)


def exists(base: Path, link: str) -> bool:
    cand = (base / link).resolve()
    if cand.exists():
        return True
    if cand.suffix == ".html" and cand.with_suffix(".md").exists():
        return True
    if cand.with_name(cand.name + ".md").exists():
        return True
    return (cand / "index.md").exists()


def main(argv: list[str]) -> int:
    files = [Path(a).resolve() for a in argv] or (
        [ROOT / f for f in DEFAULT if (ROOT / f).is_file()]
        + [f for f in sorted(DOCS.rglob("*.md")) if not is_generated_docs_file(f)]
        + sorted((ROOT / "openfdd_agent_spec").rglob("*.md")))
    bad = 0
    total = 0
    for f in files:
        for n, link in targets(f):
            if re.match(r"^(https?:|mailto:|#|\{\{|/)", link):
                continue
            total += 1
            rel = unquote(link.split("#")[0].split("?")[0])
            if rel and not exists(f.parent, rel):
                bad += 1
                print(f"{f.relative_to(ROOT)}:{n}: broken link -> {link}")
    print(f"checked {total} relative links in {len(files)} files: {bad} broken")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
