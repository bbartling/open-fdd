#!/usr/bin/env python3
"""Regenerate sql/contract/manifest.json + successor_bundle/FILES.sha256 from installed bytes.

Soft-OPEN ≠ FQ. Fails closed if a listed path is missing. pack_sha256 is the
Merkle-style digest: for each file in manifest order,
  sha256.update(path + NUL + file_sha256_hex + NUL).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "sql/contract/manifest.json"
FILES_LEDGER = ROOT / "sql/contract/successor_bundle/FILES.sha256"


def main() -> int:
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    files = []
    h = hashlib.sha256()
    for entry in m["files"]:
        path = entry["path"]
        p = ROOT / path
        if not p.is_file():
            print(f"FAIL: missing listed contract file: {path}", file=sys.stderr)
            return 1
        data = p.read_bytes()
        dig = hashlib.sha256(data).hexdigest()
        files.append({"path": path, "sha256": dig, "bytes": len(data)})
        h.update(path.encode())
        h.update(b"\0")
        h.update(dig.encode())
        h.update(b"\0")
    m["files"] = files
    m["file_count"] = len(files)
    m["pack_sha256"] = h.hexdigest()
    MANIFEST.write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    FILES_LEDGER.write_text(
        "\n".join(f"{f['sha256']}  {f['path']}" for f in files) + "\n",
        encoding="utf-8",
    )
    print(f"OK: {len(files)} files pack_sha256={m['pack_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
