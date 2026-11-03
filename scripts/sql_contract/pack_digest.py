"""Merkle-style digests for scientific pack and distribution companions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def merkle_paths(entries: Iterable[tuple[str, str]]) -> str:
    """Digest: for each (relative_path, file_sha256_hex) in order, update path+NUL+sha+NUL."""
    h = hashlib.sha256()
    for path, file_sha in entries:
        h.update(path.encode())
        h.update(b"\0")
        h.update(file_sha.encode())
        h.update(b"\0")
    return h.hexdigest()


def scientific_pack_digest(manifest: dict[str, Any]) -> str:
    pinned = str(manifest.get("pack_sha256") or "")
    recomputed = merkle_paths((e["path"], e["sha256"]) for e in manifest.get("files") or [])
    if pinned and pinned != recomputed:
        raise ValueError(
            f"scientific pack_sha256 mismatch: manifest={pinned} recomputed={recomputed}"
        )
    return recomputed


def distribution_digest(*, scientific_pack_sha256: str, companion_entries: list[dict[str, str]]) -> str:
    inner = merkle_paths((e["path"], e["sha256"]) for e in companion_entries)
    h = hashlib.sha256()
    h.update(scientific_pack_sha256.encode())
    h.update(b"\0")
    h.update(inner.encode())
    h.update(b"\0")
    return h.hexdigest()


def load_scientific_manifest(repo_or_artifact: Path) -> dict[str, Any]:
    path = repo_or_artifact / "sql/contract/manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing scientific manifest: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
