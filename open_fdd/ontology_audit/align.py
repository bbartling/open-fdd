"""223P check used by CI: vendored closure, Shifty, fail on any Violation.

    python -m open_fdd.ontology_audit.align --report ./shacl-report
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file() and (parent / "sql" / "fdd").is_dir():
            return parent
    raise FileNotFoundError("open-fdd repo root")


def default_models() -> list[Path]:
    root = repo_root()
    return [
        root / "sql" / "fdd" / "roles-223p.ttl",
        root / "open_fdd" / "ontology_audit" / "data" / "223p-import-only.ttl",
    ]


def validate_model(path: Path, *, cross_check: bool = False) -> dict:
    """Shifty on ``path`` with the vendored 223P closure. No download.

    ``conforms`` is Shifty's. A pySHACL cross-check is stored beside it.
    """
    from open_fdd.ontology_audit.closure import unknown_model_imports
    from open_fdd.ontology_audit.shacl import validate_223p
    from open_fdd.ontology_audit.sources import parse_rdf

    model = parse_rdf(path)
    unknown = unknown_model_imports(model)
    if unknown:
        raise ValueError("model owl:imports is not the pinned 223P root: " + ", ".join(unknown))
    report = validate_223p(path, cross_check="pyshacl" if cross_check else None)
    report["model"] = str(path)
    report.pop("report_text", None)
    cross = report.get("cross_check")
    if isinstance(cross, dict):
        cross.pop("report_text", None)
    return report


def validate_export(path: Path, *, cross_check: bool = False) -> dict:
    """Shifty on a Haystack export, using the local export shapes (no remote imports)."""
    from open_fdd.ontology_audit.shacl import validate_shacl, violation_count
    from open_fdd.ontology_audit.sources import parse_rdf

    report = validate_shacl(parse_rdf(path), engine="shifty", closure=None, cross_check=cross_check)
    report["model"] = str(path)
    report["shapes"] = "openfdd_export_shapes.ttl"
    report["violation_count"] = violation_count(report)
    report.pop("report_text", None)
    return report


def run(models: list[Path], export: Path | None, report_dir: Path, *, cross_check: bool = False) -> int:
    report_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    failed = False
    for path in models:
        if not path.is_file():
            raise FileNotFoundError(path)
        info = validate_model(path, cross_check=cross_check)
        reports.append(info)
        if info.get("conforms") is not True or info.get("violation_count"):
            failed = True
    if export is not None:
        info = validate_export(export, cross_check=cross_check)
        reports.append(info)
        if not info.get("available") or info.get("violation_count"):
            failed = True
    names = next((info.get("closure") for info in reports if info.get("closure")), [])
    summary = {"closure_iris": names, "models": reports, "conforms": not failed}
    text = json.dumps(summary, indent=2) + "\n"
    (report_dir / "shacl-report.json").write_text(text, encoding="utf-8")
    print(text)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m open_fdd.ontology_audit.align", description=__doc__)
    parser.add_argument("--model", type=Path, action="append", default=[],
                        help="a Turtle model that owl:imports 223P (default: the role file and the import fixture)")
    parser.add_argument("--export", type=Path,
                        default=repo_root() / "open_fdd" / "ontology_audit" / "data" / "example_building.ttl",
                        help="Haystack export checked with the local shapes (pass an empty path to skip)")
    parser.add_argument("--no-export", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--cross-check", action="store_true",
                        help="also run pySHACL advanced=True and record it; the verdict stays Shifty")
    args = parser.parse_args(argv)
    models = args.model or default_models()
    export = None if args.no_export else args.export
    try:
        return run(models, export, args.report, cross_check=args.cross_check)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"223p align: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
