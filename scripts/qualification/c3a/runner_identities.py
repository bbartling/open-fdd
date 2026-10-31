"""Four scientific runners A–D identity pins for SQL-QUAL-01."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]

# Frozen IP oracle (runner A) — do not substitute current tree.
RUNNER_A_VERSION = "4.4.9"
RUNNER_A_GIT_HEAD = "35c17ac2d4ccc9ff677f5dd8d928e786aea0e2f0"
RUNNER_A_REGISTRY_SHA256 = "b0397a06d834109a77e85599c81e7c81cbacfab7d38372503c943c1f26e1fcbf"

# Frozen old product SQL baseline (runner B) at the same release cut.
RUNNER_B_GIT_HEAD = RUNNER_A_GIT_HEAD


def _git_head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _open_fdd_tree_sha256(package_root: Path) -> str:
    digest = hashlib.sha256()
    if not package_root.is_dir():
        return ""
    for path in sorted(package_root.rglob("*.py")):
        if any(part in {".git", "__pycache__", ".venv", "venv"} for part in path.parts):
            continue
        digest.update(path.relative_to(package_root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _postgres_rules_tree_sha256(rules_dir: Path) -> str:
    digest = hashlib.sha256()
    if not rules_dir.is_dir():
        return ""
    for path in sorted(rules_dir.glob("*.sql")):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _manifest_pack_sha256(repo: Path) -> str:
    manifest = json.loads((repo / "sql" / "contract" / "manifest.json").read_text(encoding="utf-8"))
    return str(manifest.get("pack_sha256") or "")


def _pyproject_version(repo: Path) -> str:
    import tomllib

    doc = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    return str(doc.get("project", {}).get("version") or "")


def record_runner_identities(repo: Path | None = None) -> dict[str, Any]:
    """Return immutable identity record for runners A–D at the candidate checkout."""
    root = (repo or REPO).resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from scripts.stress.si_cutover import parity_chain as pc

    candidate_head = _git_head(root)
    candidate_version = _pyproject_version(root)
    candidate_tree = _open_fdd_tree_sha256(root / "open_fdd")
    candidate_pack = _manifest_pack_sha256(root)
    candidate_rules_tree = _postgres_rules_tree_sha256(root / "sql" / "fdd" / "postgres" / "rules")

    return {
        "candidate_git_head": candidate_head,
        "runners": {
            "A": {
                "label": "frozen_pandas_ip",
                "open_fdd_version": RUNNER_A_VERSION,
                "git_head": RUNNER_A_GIT_HEAD,
                "registry_sha256": RUNNER_A_REGISTRY_SHA256,
                "environment": "original_35c17ac_ip_oracle",
                "must_not_equal": {
                    "candidate_git_head": candidate_head,
                    "candidate_open_fdd_version": candidate_version,
                },
            },
            "B": {
                "label": "frozen_old_product_sql",
                "git_head": RUNNER_B_GIT_HEAD,
                "registry_sha256": RUNNER_A_REGISTRY_SHA256,
                "note": "old PG bodies pinned to 35c17ac registry ABI; not candidate pack_sha256",
                "must_not_equal": {"candidate_pack_sha256": candidate_pack},
            },
            "C": {
                "label": "candidate_pandas",
                "open_fdd_version": candidate_version,
                "git_head": candidate_head,
                "open_fdd_tree_sha256": candidate_tree,
                "import_must_live_under": str(root),
                "frozen_ip_forbidden": pc.FROZEN_IP_ORACLE_VERSION,
            },
            "D": {
                "label": "candidate_postgresql_sql",
                "git_head": candidate_head,
                "pack_sha256": candidate_pack,
                "postgres_rules_tree_sha256": candidate_rules_tree,
                "metric_units_sha256": _manifest_metric_units_sha(root),
            },
        },
    }


def _manifest_metric_units_sha(repo: Path) -> str:
    manifest = json.loads((repo / "sql" / "contract" / "manifest.json").read_text(encoding="utf-8"))
    return str(manifest.get("metric_units_sha256") or "")


def verify_runner_substitution_guard(idents: dict[str, Any]) -> list[str]:
    """Negative control: moving candidate must not be mistaken for frozen A/B."""
    errors: list[str] = []
    a = idents["runners"]["A"]
    b = idents["runners"]["B"]
    c = idents["runners"]["C"]
    d = idents["runners"]["D"]
    head = str(idents.get("candidate_git_head") or "")
    if head == a["git_head"] and c["open_fdd_version"] == a["open_fdd_version"]:
        errors.append("runner C version matches frozen A while HEAD differs — check import path")
    if head == b["git_head"]:
        errors.append("candidate HEAD must not equal frozen runner B git pin during C3a")
    if not d.get("pack_sha256"):
        errors.append("runner D missing pack_sha256")
    if c["open_fdd_version"] == a["open_fdd_version"]:
        errors.append("runner C must not ship frozen IP oracle version 4.4.9")
    return errors
