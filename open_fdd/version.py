"""Independent version axes for the Open-FDD Python package.

These are intentionally not collapsed into one “Open-FDD version” string.
``rule_catalog_hash`` / ``effective_config_hash`` are filled by
``open_fdd.catalog`` when that module is available; otherwise they are null.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

CATALOG_SCHEMA_VERSION = "open-fdd-catalog-v1"
RULE_CATALOG_VERSION = "77-sql-pack"

def _repo_root() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "VERSION").is_file() and (parent / "open_fdd").is_dir():
            return parent
    return None


def git_revision() -> str | None:
    env = os.environ.get("OPENFDD_GIT_REVISION") or os.environ.get("GITHUB_SHA")
    if env:
        return env.strip()
    root = _repo_root()
    if root is None:
        return None
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
        return out.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def package_version() -> str:
    """The PyPI package version (``importlib.metadata``), falling back to ``pyproject.toml``.

    Inside a checkout the checkout's ``pyproject.toml`` wins: the source tree is what runs, and an
    older installed copy would report a stale version.
    """
    root = _repo_root()
    if root is not None and (root / "pyproject.toml").is_file():
        m = re.search(r'^version\s*=\s*"([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"), re.M)
        if m:
            return m.group(1)
    try:
        from importlib.metadata import version

        return version("open-fdd")
    except Exception:
        return "0+unknown"


def app_version() -> str | None:
    """Open-FDD Normal Framework app version (the repo ``VERSION`` file, 5.x); None outside a checkout."""
    root = _repo_root()
    if root is None:
        return None
    try:
        return (root / "VERSION").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def release_version() -> str | None:
    """Alias of :func:`app_version` (kept for existing callers)."""
    return app_version()


def _catalog_hashes() -> tuple[str | None, str | None]:
    try:
        from open_fdd.catalog import effective_config_hash, rule_catalog_hash
    except ImportError:
        return None, None
    return rule_catalog_hash(), effective_config_hash()


def python_version() -> str:
    return package_version()


def manifest(*, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the version/identity document consumers should persist."""
    cat_hash, cfg_hash = _catalog_hashes()
    doc = {
        "open_fdd_python_version": python_version(),
        "package_version": python_version(),
        "app_version": app_version(),
        "git_revision": git_revision(),
        "release_version": app_version(),
        "rule_catalog_version": RULE_CATALOG_VERSION,
        "catalog_schema_version": CATALOG_SCHEMA_VERSION,
        "rule_catalog_hash": cat_hash,
        "effective_config_hash": cfg_hash,
    }
    if overrides:
        doc.update(overrides)
    return doc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Print Open-FDD version axes as JSON.")
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args(argv)
    payload = manifest()
    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
