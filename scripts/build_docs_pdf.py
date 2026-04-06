#!/usr/bin/env python3
"""
Build a single PDF from the Open-FDD docs (Just the Docs / Jekyll-style Markdown).

Collects all docs/*.md (respecting nav_order and parent from YAML front matter),
strips front matter, concatenates with headings, and runs Pandoc to produce
pdf/open-fdd-docs.pdf (project root pdf/ dir). Also writes a .txt file with the
same combined content in the same output dir (e.g. pdf/open-fdd-docs.txt) for
LLM context; formatting is plain (same Markdown source, no PDF styling).
Kramdown/Jekyll inline attribute lists (``{: .class }``) are stripped so PDF/txt stay clean.

Requirements:
  - pandoc (https://pandoc.org/)
  - For PDF: either
    - weasyprint (pip install weasyprint) — good quality, no LaTeX, or
    - LaTeX (e.g. texlive) for pandoc's default pdflatex

When WeasyPrint is installed only inside a virtualenv, pandoc must find the
``weasyprint`` executable: this script prepends the current Python's ``bin``
directory to ``PATH`` for the Pandoc subprocess (needed for CI and local venvs).

Usage:
  python3 scripts/build_docs_pdf.py     # writes pdf/open-fdd-docs.pdf
  python3 scripts/build_docs_pdf.py -o docs/releases/open-fdd-docs-2.0.3.pdf

The script writes a combined Markdown file (docs/_build/combined.md) and then
runs: pandoc ... -o <output> --toc --pdf-engine=weasyprint (or pdflatex).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Kramdown / Jekyll inline attribute lists (Just the Docs), e.g. {: .fs-6 .fw-400 }
_KRAMDOWN_IAL_RE = re.compile(r"\{:[^}\n]*\}\s*")

try:
    import yaml
except ImportError:
    yaml = None

# Repo layout: script in scripts/, docs in docs/, output in pdf/
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DOCS_DIR = REPO_ROOT / "docs"
PDF_DIR = REPO_ROOT / "pdf"
BUILD_DIR = DOCS_DIR / "_build"
DEFAULT_OUTPUT = PDF_DIR / "open-fdd-docs.pdf"


def parse_front_matter(path: Path) -> tuple[dict, str]:
    """Read file; return (front_matter_dict, body). Front matter is YAML between first --- and second ---."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for i in range(1, min(len(lines), 25)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    yaml_block = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :]).lstrip()
    try:
        fm = yaml.safe_load(yaml_block) if yaml_block.strip() else {}
    except Exception:
        fm = {}
    return (fm or {}), body


def strip_kramdown_ial(text: str) -> str:
    """Remove Kramdown/Jekyll `{: ... }` blocks; Pandoc and plain text keep them as junk."""
    return _KRAMDOWN_IAL_RE.sub("", text)


def collect_md_files(docs_dir: Path) -> list[Path]:
    """All .md files under docs/, excluding 404 and _build."""
    out: list[Path] = []
    for f in sorted(docs_dir.rglob("*.md")):
        if f.name == "404.md":
            continue
        if "_build" in f.parts:
            continue
        out.append(f)
    return out


def section_order_key(
    path: Path,
    front_matter: dict,
    title_to_nav: dict[str, int],
) -> tuple[int, int, str]:
    """Sort key: (section_nav_order, page_nav_order, path_str)."""
    parent = front_matter.get("parent") or ""
    nav = front_matter.get("nav_order")
    if nav is None:
        nav = 999
    try:
        nav = int(nav)
    except (TypeError, ValueError):
        nav = 999
    if parent:
        section_nav = title_to_nav.get(parent, 999)
    else:
        section_nav = nav
    return (section_nav, nav, str(path))


def build_title_to_nav(docs_dir: Path, files: list[Path]) -> dict[str, int]:
    """Map page title to nav_order for parent lookup (only for pages that define nav_order)."""
    title_to_nav: dict[str, int] = {}
    for path in files:
        fm, _ = parse_front_matter(path)
        title = fm.get("title")
        nav = fm.get("nav_order")
        if title and nav is not None:
            try:
                title_to_nav[title] = int(nav)
            except (TypeError, ValueError):
                pass
    return title_to_nav


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build Open-FDD docs into a single PDF (Pandoc + weasyprint or pdflatex)."
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output PDF path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--keep-md",
        action="store_true",
        help="Keep combined Markdown in docs/_build/combined.md",
    )
    parser.add_argument(
        "--pdf-engine",
        choices=["weasyprint", "pdflatex", "xelatex"],
        default="weasyprint",
        help="Pandoc PDF engine (default: weasyprint; use pdflatex for best typography if LaTeX installed)",
    )
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="Only write combined.md, do not run Pandoc",
    )
    args = parser.parse_args()

    if not DOCS_DIR.is_dir():
        print(f"Docs directory not found: {DOCS_DIR}", file=sys.stderr)
        return 1

    if yaml is None:
        print("PyYAML is required. pip install pyyaml", file=sys.stderr)
        return 1

    files = collect_md_files(DOCS_DIR)
    title_to_nav = build_title_to_nav(DOCS_DIR, files)

    # Sort by (section_nav, page_nav, path)
    def sort_key(path: Path) -> tuple[int, int, str]:
        fm, _ = parse_front_matter(path)
        return section_order_key(path, fm, title_to_nav)

    sorted_files = sorted(files, key=sort_key)

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    combined_path = BUILD_DIR / "combined.md"
    now = datetime.now()
    build_date = now.strftime(f"%B {now.day}, %Y")
    parts: list[str] = []
    parts.append("% Open-FDD Documentation\n")
    parts.append("% Generated by scripts/build_docs_pdf.py\n")
    parts.append(f"% {build_date}\n\n")
    parts.append(f"*Generated {build_date}*\n\n")
    parts.append("---\n\n")

    for path in sorted_files:
        fm, body = parse_front_matter(path)
        title = fm.get("title") or path.stem.replace("-", " ").replace("_", " ").title()
        if fm.get("nav_exclude"):
            continue
        # One top-level heading per page so TOC is clean
        parts.append(f"# {title}\n\n")
        parts.append(strip_kramdown_ial(body))
        if not body.endswith("\n"):
            parts.append("\n")
        parts.append("\n\n")

    combined_md = "".join(parts)
    combined_path.write_text(combined_md, encoding="utf-8")
    print(f"Wrote {len(sorted_files)} pages to {combined_path}")

    # Same content as a .txt in the same output dir for LLM context (no need to look pretty).
    txt_output = args.output.with_suffix(".txt")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    txt_output.write_text(combined_md, encoding="utf-8")
    print(f"Wrote LLM context text to {txt_output}")

    if args.no_pdf:
        print("Skipping PDF (--no-pdf).")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "pandoc",
        str(combined_path),
        "-o",
        str(args.output),
        "--toc",
        "--number-sections",
        f"--pdf-engine={args.pdf_engine}",
        "-V",
        "documentclass=article",
        "-V",
        "papersize=letter",
        "-V",
        "geometry:margin=1in",
        "-V",
        f"date={build_date}",
    ]
    print(f"Running: {' '.join(cmd)}")
    env = os.environ.copy()
    py_bin = str(Path(sys.executable).resolve().parent)
    if py_bin:
        env["PATH"] = py_bin + os.pathsep + env.get("PATH", "")
    try:
        subprocess.run(cmd, check=True, cwd=REPO_ROOT, env=env)
    except FileNotFoundError:
        print("pandoc not found. Install pandoc: https://pandoc.org/installing.html", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        if args.pdf_engine == "weasyprint":
            print(
                "WeasyPrint PDF failed. Install: pip install weasyprint",
                file=sys.stderr,
            )
            print("Or use LaTeX: python scripts/build_docs_pdf.py --pdf-engine=pdflatex", file=sys.stderr)
        return e.returncode

    print(f"PDF written to {args.output}")
    if not args.keep_md:
        combined_path.unlink(missing_ok=True)
        if BUILD_DIR.exists() and not any(BUILD_DIR.iterdir()):
            BUILD_DIR.rmdir()
    return 0


if __name__ == "__main__":
    sys.exit(main())
