#!/usr/bin/env python3
"""Fail closed if wrapper cleanup changes already-evaluated ZAP evidence.

Snapshots contain path digests and byte hashes, never file contents. Keep the
snapshot in the runner's private directory outside the evidence tree. This is
an integrity check of wrapper processing, not scanner or security qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

SNAPSHOT_SCHEMA = "openfdd.zap_artifact_snapshot.v1"
GUARD_SUITE = "openfdd.zap_wrapper_artifact_integrity.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class IntegrityError(ValueError):
    """Missing, unreadable, unsafe or changed evidence (no sensitive detail)."""


def snapshot_tree(root: Path) -> dict[str, dict[str, Any]]:
    """Hash regular files; refuse symlinks and unreadable/nonregular artifacts."""
    if root.is_symlink() or not root.is_dir():
        raise IntegrityError("artifact_root_unavailable")
    files: dict[str, dict[str, Any]] = {}
    try:
        for directory, dirs, names in os.walk(root, followlinks=False, onerror=_walk_error):
            parent = Path(directory)
            if any((parent / name).is_symlink() for name in dirs):
                raise IntegrityError("artifact_symlink_refused")
            for name in names:
                path = parent / name
                if path.is_symlink() or not path.is_file():
                    raise IntegrityError("artifact_nonregular_refused")
                digest = hashlib.sha256()
                size = 0
                with path.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                path_digest = hashlib.sha256(os.fsencode(path.relative_to(root))).hexdigest()
                files[path_digest] = {"sha256": digest.hexdigest(), "bytes": size}
    except OSError as exc:
        raise IntegrityError("artifact_unreadable") from exc
    return files


def _walk_error(_error: OSError) -> None:
    raise IntegrityError("artifact_directory_unreadable")


def _atomic_json(path: Path, payload: dict[str, Any], *, exclusive: bool = False) -> None:
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if exclusive:
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out:
            out.write(data)
        return
    temporary = path.with_name(".integrity-" + uuid.uuid4().hex)
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out:
            out.write(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_state_path(root: Path, state: Path) -> None:
    if state.resolve().is_relative_to(root.resolve()):
        raise IntegrityError("snapshot_must_be_outside_artifacts")


def save_snapshot(root: Path, state: Path) -> None:
    _validate_state_path(root, state)
    _atomic_json(state, {
        "schema": SNAPSHOT_SCHEMA,
        "root_digest": hashlib.sha256(os.fsencode(root.resolve())).hexdigest(),
        "files": snapshot_tree(root),
    }, exclusive=True)


def load_snapshot(root: Path, state: Path) -> dict[str, dict[str, Any]]:
    _validate_state_path(root, state)
    if state.is_symlink():
        raise IntegrityError("snapshot_symlink_refused")
    data = json.loads(state.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"schema", "root_digest", "files"} or data["schema"] != SNAPSHOT_SCHEMA:
        raise IntegrityError("snapshot_schema_invalid")
    if data["root_digest"] != hashlib.sha256(os.fsencode(root.resolve())).hexdigest():
        raise IntegrityError("snapshot_root_mismatch")
    files = data["files"]
    if not isinstance(files, dict):
        raise IntegrityError("snapshot_files_invalid")
    for key, value in files.items():
        if not isinstance(key, str) or not _SHA256.fullmatch(key) or not isinstance(value, dict):
            raise IntegrityError("snapshot_entry_invalid")
        if set(value) != {"sha256", "bytes"} or not isinstance(value["sha256"], str) or not _SHA256.fullmatch(value["sha256"]):
            raise IntegrityError("snapshot_entry_invalid")
        if not isinstance(value["bytes"], int) or isinstance(value["bytes"], bool) or value["bytes"] < 0:
            raise IntegrityError("snapshot_entry_invalid")
    return files


def compare_snapshot(root: Path, state: Path) -> dict[str, int]:
    before, after = load_snapshot(root, state), snapshot_tree(root)
    return {
        "before_files": len(before),
        "after_files": len(after),
        "added": len(after.keys() - before.keys()),
        "deleted": len(before.keys() - after.keys()),
        "changed": sum(before[key] != after[key] for key in before.keys() & after.keys()),
    }


def invalidate_claims(root: Path, verdicts: list[Path]) -> int:
    """Replace top-level wrapper verdicts with ERROR; unlink if replacement fails.

    No prior contents are read, copied, printed or retained as a qualified claim.
    Other scanner evidence remains untouched; no hashes are silently repaired.
    """
    failures = 0
    for path in verdicts:
        if path.parent.resolve() != root.resolve():
            failures += 1
            continue
        try:
            _atomic_json(path, {
                "suite": GUARD_SUITE, "status": "ERROR", "mode": "artifact_integrity",
                "artifact_integrity_verified": False,
                "notes": "Wrapper cleanup changed or could not verify evaluated evidence; prior qualification is invalid.",
            })
        except OSError:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                failures += 1
    return failures


def run_guard(*, action: str, root: Path, state: Path, report: Path,
              verdicts: list[Path], redaction_failed: bool = False) -> int:
    counts: dict[str, int] = {}
    report_safe = report.parent.resolve() == root.resolve() and report not in verdicts
    try:
        if not report_safe:
            raise IntegrityError("report_path_invalid")
        if action == "snapshot":
            save_snapshot(root, state)
            return 0
        counts = compare_snapshot(root, state)
        if redaction_failed:
            raise IntegrityError("redaction_command_failed")
        if any(counts[key] for key in ("added", "deleted", "changed")):
            raise IntegrityError("evaluated_artifacts_changed")
        _atomic_json(report, {
            "suite": GUARD_SUITE, "status": "PASS", "artifact_integrity_verified": True,
            "scope": "wrapper_cleanup_byte_integrity_only", "counts": counts,
        })
        return 0
    except (OSError, ValueError, UnicodeError):
        # Exception strings and artifact paths can contain sensitive values.
        # Persist only fixed reason codes and counts, never raw errors/content.
        reason = "artifact_integrity_failed"
    failures = invalidate_claims(root, verdicts)
    if report_safe:
        try:
            _atomic_json(report, {
                "suite": GUARD_SUITE, "status": "ERROR", "artifact_integrity_verified": False,
                "reason": reason, "counts": counts, "claim_invalidation_failures": failures,
            })
        except OSError:
            pass  # Exit 1 remains authoritative when the artifact directory is unwritable.
    print("ERROR: evaluated ZAP artifact integrity failed; qualification invalid", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("snapshot", "verify"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--verdict", required=True, action="append", type=Path)
    parser.add_argument("--redaction-failed", action="store_true")
    args = parser.parse_args(argv)
    return run_guard(action=args.action, root=args.root, state=args.state, report=args.report,
                     verdicts=args.verdict, redaction_failed=args.redaction_failed)


if __name__ == "__main__":
    raise SystemExit(main())
