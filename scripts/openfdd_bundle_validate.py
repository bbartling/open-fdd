#!/usr/bin/env python3
"""Offline Open-FDD Engineering Bundle validator (#763 Phase 1 slice).

Usage:
  python3 scripts/openfdd_bundle_validate.py validate path/to/bundle.zip
  ./scripts/openfdd-bundle validate path/to/bundle.zip

Does NOT run inside openfdd-central. No pandas/sklearn required for structural checks.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "openfdd_bundle_validation_v1"
SECRET_HINTS = re.compile(
    r"(password|secret|token|api[_-]?key|authorization|private[_-]?key)",
    re.I,
)
ABS_PATH = re.compile(r"(^|[\s\"'])(/home/|/Users/|[A-Za-z]:\\\\|/var/openfdd/)")


def _status(errors: list[str], warnings: list[str]) -> str:
    if errors:
        return "NOT_READY"
    if warnings:
        return "READY_WITH_WARNINGS"
    return "READY"


def _fingerprint(z: zipfile.ZipFile) -> str:
    h = hashlib.sha256()
    for name in sorted(z.namelist()):
        if name.endswith("/"):
            continue
        h.update(name.encode())
        h.update(z.read(name))
    return h.hexdigest()[:32]


def _load_manifest(z: zipfile.ZipFile) -> dict[str, Any] | None:
    for candidate in ("MANIFEST.json", "manifest.json"):
        if candidate in z.namelist():
            return json.loads(z.read(candidate).decode("utf-8", errors="replace"))
    return None


def _check_secrets_and_paths(
    name: str, raw: bytes, errors: list[str], warnings: list[str]
) -> None:
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return
    if SECRET_HINTS.search(name) or SECRET_HINTS.search(text[:4000]):
        # Heuristic — flag as warning unless clearly a credential file name.
        if SECRET_HINTS.search(name):
            errors.append(f"possible secret in path: {name}")
        else:
            warnings.append(f"secret-like token in {name}")
    if ABS_PATH.search(text[:8000]):
        errors.append(f"host-specific absolute path in {name}")


def _validate_csv(name: str, raw: bytes, errors: list[str], warnings: list[str]) -> None:
    try:
        text = raw.decode("utf-8", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
    except Exception as exc:
        errors.append(f"CSV unreadable {name}: {exc}")
        return
    if not rows:
        warnings.append(f"empty CSV {name}")
        return
    header = rows[0]
    if not header:
        errors.append(f"CSV missing header {name}")


def _validate_parquet_magic(name: str, raw: bytes, errors: list[str]) -> None:
    # PAR1 magic at start and end — structural only (no pyarrow required).
    if len(raw) < 8 or raw[:4] != b"PAR1" or raw[-4:] != b"PAR1":
        errors.append(f"Parquet magic missing {name}")


def validate_zip(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    files_checked = 0
    ml_readiness: dict[str, Any] = {
        "has_manifest": False,
        "has_readme": False,
        "csv_files": 0,
        "parquet_files": 0,
        "note": "Phase-1 structural validator only (#763); ML features/labels/splits not required yet",
    }

    if not path.is_file():
        return {
            "schema_version": SCHEMA,
            "status": "NOT_READY",
            "errors": [f"file not found: {path}"],
            "warnings": [],
            "files_checked": 0,
            "content_fingerprint": None,
            "ml_readiness": ml_readiness,
        }

    try:
        z = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile as exc:
        return {
            "schema_version": SCHEMA,
            "status": "NOT_READY",
            "errors": [f"ZIP open failed: {exc}"],
            "warnings": [],
            "files_checked": 0,
            "content_fingerprint": None,
            "ml_readiness": ml_readiness,
        }

    with z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        fingerprint = _fingerprint(z)
        manifest = _load_manifest(z)
        if manifest is None:
            errors.append("MANIFEST.json missing")
        else:
            ml_readiness["has_manifest"] = True
            # Manifest may list files as list[str] or dict with path keys.
            listed: list[str] = []
            if isinstance(manifest.get("files"), list):
                for item in manifest["files"]:
                    if isinstance(item, str):
                        listed.append(item)
                    elif isinstance(item, dict) and "path" in item:
                        listed.append(str(item["path"]))
            elif isinstance(manifest.get("artifacts"), dict):
                listed.extend(str(v) for v in manifest["artifacts"].values() if isinstance(v, str))
            for rel in listed:
                rel_n = rel.lstrip("./")
                if rel_n not in names and rel not in names:
                    errors.append(f"manifest path missing from ZIP: {rel}")

        if any(n.lower().endswith("readme.md") or n == "README.md" for n in names):
            ml_readiness["has_readme"] = True
        else:
            warnings.append("README.md missing")

        for name in names:
            files_checked += 1
            raw = z.read(name)
            _check_secrets_and_paths(name, raw, errors, warnings)
            lower = name.lower()
            if lower.endswith(".csv"):
                ml_readiness["csv_files"] += 1
                _validate_csv(name, raw, errors, warnings)
            elif lower.endswith(".parquet"):
                ml_readiness["parquet_files"] += 1
                _validate_parquet_magic(name, raw, errors)
            elif lower.endswith(".json"):
                try:
                    json.loads(raw.decode("utf-8", errors="replace"))
                except Exception as exc:
                    errors.append(f"JSON invalid {name}: {exc}")

        # Timestamp sanity on MANIFEST export time if present
        if manifest:
            for key in ("exported_at", "export_timestamp", "generated_at"):
                val = manifest.get(key)
                if isinstance(val, str) and val:
                    try:
                        datetime.fromisoformat(val.replace("Z", "+00:00"))
                    except Exception:
                        warnings.append(f"manifest {key} not ISO-8601: {val!r}")

    return {
        "schema_version": SCHEMA,
        "status": _status(errors, warnings),
        "errors": errors,
        "warnings": warnings,
        "files_checked": files_checked,
        "content_fingerprint": fingerprint,
        "ml_readiness": ml_readiness,
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "path": str(path),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Validate Open-FDD engineering bundle ZIP (#763)")
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="Validate a bundle ZIP")
    v.add_argument("zip_path", type=Path)
    v.add_argument("--json", action="store_true", help="Print full JSON report (default)")
    args = p.parse_args(argv)

    if args.cmd == "validate":
        report = validate_zip(args.zip_path)
        print(json.dumps(report, indent=2))
        return 0 if report["status"] != "NOT_READY" else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
