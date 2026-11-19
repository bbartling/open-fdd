"""The PyPI long description is README.md; relative links do not resolve on pypi.org (#1662)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_links_are_absolute():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    targets = re.findall(r"\]\(([^)\s]+)\)", text) + re.findall(r'(?:src|href)="([^"]+)"', text)
    relative = [t for t in targets if not re.match(r"(https?:|mailto:|#)", t)]
    assert relative == [], f"README.md links that break on pypi.org: {relative}"


def test_ml_download_help_states_size_and_source():
    from open_fdd.ml.cli import build_parser

    parser = build_parser()
    sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    desc = sub.choices["download"].description
    assert "1.1 GB" in desc and "10.25984/1881324" in desc
