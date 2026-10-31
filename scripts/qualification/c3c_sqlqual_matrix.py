"""Machine-readable C3 SQL-QUAL matrix (harness-only, schema c3-sqlqual-matrix-v1)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

Status = Literal["PASS", "FAIL", "BLOCKED", "PENDING", "SKIPPED", "ERROR"]

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "c3-sqlqual-matrix-v1"


@dataclass
class CheckCell:
    id: str
    phase: str
    status: Status
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def git_head() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def sha256_paths(paths: list[Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in paths:
        if path.is_file():
            out[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def qual_id_from_check(check_id: str) -> str:
    if not check_id.startswith("SQL-QUAL-"):
        return check_id
    rest = check_id[len("SQL-QUAL-") :]
    token = rest.split("-", 1)[0]
    return f"SQL-QUAL-{token}"


@dataclass
class MatrixDocument:
    schema: str = SCHEMA
    generated_at: str = ""
    candidate_git_sha: str = ""
    identities: dict[str, Any] = field(default_factory=dict)
    cells: list[CheckCell] = field(default_factory=list)

    def add(self, cell: CheckCell) -> None:
        self.cells.append(cell)

    def summary_table(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for cell in self.cells:
            qual = qual_id_from_check(cell.id)
            rows.append(
                {
                    "sql_qual_id": qual,
                    "check_id": cell.id,
                    "status": cell.status,
                    "summary": cell.summary,
                }
            )
        return rows

    def counts_by_qual(self) -> dict[str, dict[str, int]]:
        buckets: dict[str, dict[str, int]] = {}
        for cell in self.cells:
            qual = qual_id_from_check(cell.id)
            bucket = buckets.setdefault(qual, {})
            bucket[cell.status] = bucket.get(cell.status, 0) + 1
        return buckets

    def exit_code(self) -> int:
        for cell in self.cells:
            if cell.status in ("FAIL", "ERROR"):
                return 1
        required = [c for c in self.cells if c.status not in ("PENDING", "SKIPPED", "BLOCKED")]
        if not required:
            return 2
        return 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "generated_at": self.generated_at,
            "candidate_git_sha": self.candidate_git_sha,
            "identities": self.identities,
            "cells": [c.to_dict() for c in self.cells],
            "summary_by_qual_id": self.counts_by_qual(),
            "summary_table": self.summary_table(),
        }

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")


def new_matrix(*, identities: dict[str, Any] | None = None) -> MatrixDocument:
    return MatrixDocument(
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        candidate_git_sha=git_head(),
        identities=identities or {},
    )
