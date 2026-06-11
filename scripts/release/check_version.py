#!/usr/bin/env python3
"""Verify Open-FDD package version consistency (local + tag release CI)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[2]
PEP440 = re.compile(
    r"^(\d+!)?(\d+)(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?$",
    re.IGNORECASE,
)


def _read_pyproject_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"]).strip()


def _read_init_version() -> str:
    text = (ROOT / "open_fdd" / "__init__.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("open_fdd/__init__.py: __version__ not found")


def _normalize_tag(tag: str) -> str:
    tag = tag.strip()
    if tag.startswith("open-fdd-v"):
        return tag[len("open-fdd-v") :]
    if tag.startswith("v"):
        return tag[1:]
    return tag


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Git tag to compare (e.g. v3.0.30 or open-fdd-v3.0.30)")
    args = parser.parse_args(argv)

    pkg = _read_pyproject_version()
    init = _read_init_version()
    errors: list[str] = []

    if pkg != init:
        errors.append(f"pyproject.toml version {pkg!r} != open_fdd.__version__ {init!r}")
    if not PEP440.match(pkg):
        errors.append(f"version {pkg!r} is not PEP 440 compatible")

    if args.tag:
        tag_ver = _normalize_tag(args.tag)
        if tag_ver != pkg:
            errors.append(f"tag version {tag_ver!r} != package version {pkg!r}")

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    print(f"OK: open-fdd {pkg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
