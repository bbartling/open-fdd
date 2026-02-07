#!/usr/bin/env python3
"""
Generate API reference from open_fdd docstrings.

Usage:
    python scripts/generate_api_docs.py

Output: docs/api/generated.md (append to or replace public.md as needed)

This script uses pydoc to extract docstrings. For full Sphinx-style output,
use: sphinx-build -b html docs_src docs_html
"""

import os
import pydoc
import sys

# Add project root to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, ROOT)


def main():
    """Generate API docs from open_fdd."""
    try:
        import open_fdd
        import open_fdd.engine
        import open_fdd.reports
    except ImportError as e:
        print(f"Import error: {e}")
        return 1

    out_path = os.path.join(ROOT, "docs", "api", "generated.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("---\n")
        f.write("title: Generated API (from docstrings)\n")
        f.write("nav_order: 2\n")
        f.write("parent: API Reference\n")
        f.write("---\n\n")
        f.write("# Generated API\n\n")
        f.write(
            "*Auto-generated from docstrings. Run `python scripts/generate_api_docs.py` to refresh.*\n\n"
        )

        for mod_name in ["open_fdd", "open_fdd.engine", "open_fdd.reports"]:
            f.write(f"## {mod_name}\n\n")
            f.write("```\n")
            text = pydoc.plain(pydoc.render_doc(mod_name, renderer=pydoc.plaintext))
            # Limit length, avoid huge output
            f.write(text[:8000] if len(text) > 8000 else text)
            f.write("\n```\n\n")

    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
