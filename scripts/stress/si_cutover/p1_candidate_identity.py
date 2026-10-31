"""External P1 candidate oracle identity pins (git rev + open_fdd tree hash)."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


def open_fdd_tree_sha256(package_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(package_root.rglob("*.py")):
        if any(part in {".git", "__pycache__", ".venv", "venv"} for part in path.parts):
            continue
        digest.update(path.relative_to(package_root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def git_head_rev(repo: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(repo.resolve()), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return ""


def compute_repo_candidate_pins(repo: Path) -> tuple[str, str]:
    """Pins suitable for OPENFDD_P1_* env (computed outside parity_chain callers)."""
    pkg = repo / "open_fdd"
    tree = open_fdd_tree_sha256(pkg) if pkg.is_dir() else ""
    return git_head_rev(repo), tree


@dataclass(frozen=True)
class P1IdentityPins:
    expected_candidate_rev: str | None = None
    expected_open_fdd_tree_sha256: str | None = None
    require_external: bool = False


def pins_from_environment() -> P1IdentityPins:
    rev = os.environ.get("OPENFDD_P1_EXPECTED_CANDIDATE_REV", "").strip() or None
    tree = os.environ.get("OPENFDD_P1_EXPECTED_OPEN_FDD_TREE_SHA256", "").strip() or None
    require_raw = os.environ.get("OPENFDD_P1_REQUIRE_EXTERNAL_IDENTITY_PINS", "").strip().lower()
    require = require_raw in {"1", "true", "yes", "on"}
    return P1IdentityPins(
        expected_candidate_rev=rev,
        expected_open_fdd_tree_sha256=tree,
        require_external=require,
    )
