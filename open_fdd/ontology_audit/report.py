"""Write audit / doctor reports: JSON (machine), CSV and XLSX (reviewer), Markdown (summary). Deterministic."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from open_fdd.ontology_audit.audit import STATUSES, AuditRow, summary

AUDIT_COLUMNS = ["row", "category", "requirement", "candidate_uri", "status", "reason", "term_kind", "label",
                 "evidence", "vocabulary", "version", "sha256", "candidates", "graph_uses", "reviewer_notes",
                 "reviewer_decision"]


def _cell(row: dict[str, Any], key: str) -> Any:
    v = row.get(key)
    if key == "candidates":
        return "; ".join(f"{c['iri']} ({c['score']})" for c in v or [])
    return "" if v is None else v


def write_audit(rows: list[AuditRow], sources: list, out: Path, *, xlsx: bool = True) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    dicts = [r.to_dict() for r in rows]
    paths = {"json": out / "audit.json", "csv": out / "audit.csv"}
    payload = {"statuses": STATUSES, "summary": summary(rows),
               "sources": [{k: v for k, v in s.to_dict().items()} for s in sources], "requirements": dicts}
    paths["json"].write_text(json.dumps(payload, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    with open(paths["csv"], "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(AUDIT_COLUMNS)
        for d in dicts:
            w.writerow([_cell(d, k) for k in AUDIT_COLUMNS])
    if xlsx:
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook()
        ws = wb.active
        ws.title = "Audit"
        ws.append(AUDIT_COLUMNS)
        for d in dicts:
            ws.append([_cell(d, k) for k in AUDIT_COLUMNS])
        for c in ws[1]:
            c.font = Font(bold=True)
        ws.freeze_panes = "A2"
        src = wb.create_sheet("Sources")
        keys = ["name", "vocabulary", "version", "status", "detail", "url", "sha256", "license", "path"]
        src.append(keys)
        for s in sources:
            d = s.to_dict()
            src.append([str(d.get(k, "")) for k in keys])
        legend = wb.create_sheet("Statuses")
        legend.append(["status", "meaning"])
        for k, v in STATUSES.items():
            legend.append([k, v])
        wb.properties.creator = "open-fdd-ontology-audit"
        paths["xlsx"] = out / "audit.xlsx"
        wb.save(paths["xlsx"])
    return paths


def write_doctor(report, out: Path, shacl: dict[str, Any] | None = None) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    if shacl is not None:
        data["shacl"] = shacl
    paths = {"json": out / "doctor.json", "md": out / "doctor.md", "csv": out / "terms.csv"}
    paths["json"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    keys = ["iri", "name", "used_as", "uses", "classification", "vocabulary", "defined"]
    with open(paths["csv"], "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(keys)
        for t in report.terms:
            w.writerow([t[k] for k in keys])
    lines = ["# Model doctor", "", f"{report.triples} triples, {report.points} points.", "",
             "| Classification / defined | Terms |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in report.counts().items()]
    lines += ["", "## Problems", ""] + ([f"- {p}" for p in report.problems] or ["None."])
    if report.role_bindings:
        lines += ["", "## Explicit roles (ofddRole)", "", "| Equipment | Role | Points |", "|---|---|---|"]
        lines += [f"| {b['equip']} | {b['role']} | {', '.join(b['points'])} |" for b in report.role_bindings]
    if shacl is not None:
        lines += ["", "## SHACL", ""]
        if not shacl["available"]:
            lines.append(shacl["detail"])
        else:
            lines.append("Conforms." if shacl["conforms"] else f"{len(shacl['violations'])} violation(s):")
            lines += [f"- {v['focus']} {v['path']}: {v['message']}" for v in shacl["violations"]]
    lines += ["", "## Competency queries", ""]
    lines += [f"- `{name}`: {len(rows)} row(s)" for name, rows in report.queries.items()]
    paths["md"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    return paths
