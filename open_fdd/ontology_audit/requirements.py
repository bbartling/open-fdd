"""Editable requirements sheet (CSV or XLSX): one modeling requirement per row."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

COLUMNS = ("category", "requirement", "description", "candidate_uri", "vocabulary", "reviewer_notes")
ALIASES = {"candidate uri": "candidate_uri", "candidate_uri": "candidate_uri", "uri": "candidate_uri",
           "reviewer notes": "reviewer_notes", "notes": "reviewer_notes"}


@dataclass
class Requirement:
    row: int
    category: str = ""
    requirement: str = ""
    description: str = ""
    candidate_uri: str = ""
    vocabulary: str = ""
    reviewer_notes: str = ""
    extra: dict[str, str] = field(default_factory=dict)


def _norm(header: str) -> str:
    key = " ".join(str(header or "").strip().lower().replace("-", " ").split())
    return ALIASES.get(key, key.replace(" ", "_"))


def _rows_from(path: Path) -> list[list[str]]:
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [["" if v is None else str(v) for v in r] for r in ws.iter_rows(values_only=True)]
        wb.close()
        return rows
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [list(r) for r in csv.reader(f)]


def read_requirements(path: str | Path) -> list[Requirement]:
    """Read the first sheet / the CSV. Needs a ``requirement`` column; the others are optional."""
    path = Path(path)
    rows = _rows_from(path)
    if not rows:
        raise ValueError(f"{path}: empty requirements file")
    header = [_norm(h) for h in rows[0]]
    if "requirement" not in header:
        raise ValueError(f"{path}: needs a 'requirement' column (columns: {', '.join(COLUMNS)})")
    out = []
    for i, values in enumerate(rows[1:], start=2):
        cells = {h: (values[j].strip() if j < len(values) and values[j] is not None else "")
                 for j, h in enumerate(header) if h}
        if not any(cells.values()):
            continue
        known = {k: cells.get(k, "") for k in COLUMNS}
        extra = {k: v for k, v in cells.items() if k not in COLUMNS}
        out.append(Requirement(row=i, extra=extra, **known))
    return out
