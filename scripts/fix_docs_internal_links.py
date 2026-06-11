#!/usr/bin/env python3
"""Rewrite fragile relative Markdown links to Jekyll {% link %} tags (baseurl-safe)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"

GITHUB_SCRIPTS_SECURITY = (
    "https://github.com/bbartling/open-fdd/blob/master/scripts/security/README.md"
)

LINK_RE = re.compile(r"(!?\[)([^\]]+)(\]\()([^)]+)(\))")

# href -> docs-relative markdown (manual overrides).
OVERRIDES: dict[str, str] = {
    "fault-codes/chiller-plant.md": "fault-codes/index.md",
    "../fault-codes/chiller-plant.md": "fault-codes/index.md",
}


def _resolve_target(from_file: Path, href: str) -> tuple[str, str] | None:
    """Return (docs_rel_md_path, anchor_suffix) or None if external/skip."""
    href = href.strip()
    if not href or href.startswith(("http://", "https://", "mailto:", "#")):
        return None
    if href.startswith("/"):
        path_part, _, anchor = href.partition("#")
        path_part = path_part.strip("/")
        if not path_part:
            md = "index.md"
        else:
            cand = DOCS_DIR / path_part
            if (cand / "index.md").is_file():
                md = f"{path_part}/index.md"
            elif cand.with_suffix(".md").is_file():
                md = f"{path_part}.md"
            elif (DOCS_DIR / f"{path_part}.md").is_file():
                md = f"{path_part}.md"
            else:
                md = f"{path_part}/index.md"
        return md, (f"#{anchor}" if anchor else "")

    if href in OVERRIDES:
        base, _, anchor = OVERRIDES[href].partition("#")
        _, _, a2 = href.partition("#")
        return base, (f"#{a2}" if a2 else "")

    path_part, _, anchor = href.partition("#")
    if path_part in OVERRIDES:
        return OVERRIDES[path_part], (f"#{anchor}" if anchor else "")

    if path_part.endswith(".md"):
        resolved = (from_file.parent / path_part).resolve()
    else:
        resolved = (from_file.parent / path_part).resolve()
        if resolved.with_suffix(".md").is_file():
            resolved = resolved.with_suffix(".md")
        elif (resolved / "index.md").is_file():
            resolved = resolved / "index.md"
        elif resolved.is_file():
            pass
        else:
            # bare name -> sibling .md
            sib = from_file.parent / f"{path_part}.md"
            if sib.is_file():
                resolved = sib
            else:
                sib_index = from_file.parent / path_part / "index.md"
                if sib_index.is_file():
                    resolved = sib_index

    try:
        rel = resolved.relative_to(DOCS_DIR)
    except ValueError:
        # repo paths like ../../scripts/security/README.md
        if "scripts/security/README.md" in path_part.replace("\\", "/"):
            return "__github_scripts_security__", ""
        return None

    if rel.suffix != ".md":
        return None
    return rel.as_posix(), (f"#{anchor}" if anchor else "")


def _jekyll_link(md_rel: str, anchor: str) -> str:
    if md_rel == "__github_scripts_security__":
        return GITHUB_SCRIPTS_SECURITY
    return f"{{% link {md_rel} %}}{anchor}"


def fix_file(path: Path, *, dry_run: bool = False) -> int:
    text = path.read_text(encoding="utf-8")
    changes = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal changes
        prefix, label, mid, href, suffix = m.groups()
        if prefix.startswith("!"):
            return m.group(0)
        if "github.com" in href or href.startswith("{% link"):
            return m.group(0)
        if "../../scripts/security/README.md" in href or href.endswith("scripts/security/README.md"):
            changes += 1
            return f"{prefix}{label}{mid}{GITHUB_SCRIPTS_SECURITY}{suffix}"
        resolved = _resolve_target(path, href)
        if not resolved:
            return m.group(0)
        md_rel, anchor = resolved
        new_href = _jekyll_link(md_rel, anchor)
        if new_href == href:
            return m.group(0)
        changes += 1
        return f"{prefix}{label}{mid}{new_href}{suffix}"

    new_text = LINK_RE.sub(repl, text)
    if changes and not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return changes


def main() -> int:
    dry = "--dry-run" in sys.argv
    total = 0
    for md in sorted(DOCS_DIR.rglob("*.md")):
        if "_build" in md.parts or md.name == "404.md":
            continue
        if "development" in md.parts:
            continue
        n = fix_file(md, dry_run=dry)
        if n:
            print(f"{'would fix' if dry else 'fixed'} {n:3d}  {md.relative_to(REPO_ROOT)}")
            total += n
    print(f"{'Would change' if dry else 'Changed'} {total} link(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
