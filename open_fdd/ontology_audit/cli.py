"""``open-fdd-ontology-audit``: requirements coverage audit and model doctor, offline-first, read-only.

    open-fdd-ontology-audit requirements.xlsx --out reports                       # offline, cached sources
    open-fdd-ontology-audit requirements.xlsx --refresh --out reports             # download the pinned sources once
    open-fdd-ontology-audit requirements.csv --graph building.ttl --shacl --out reports
    open-fdd-ontology-audit --graph building.ttl --out reports                   # doctor only
    open-fdd-ontology-audit --example --out reports                              # the shipped synthetic example
    open-fdd-ontology-audit --from-nf --out reports                              # optional: NF box (open-fdd[nf])
    open-fdd-ontology-audit --sources                                            # list the pinned sources

Exit code 0 on success (whatever the statuses), 2 on an error.
"""
from __future__ import annotations

import argparse
import json
import sys
from importlib.resources import as_file, files
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="open-fdd-ontology-audit", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("requirements", nargs="?", type=Path, help="CSV or XLSX: category, requirement, description, "
                   "candidate_URI, vocabulary, reviewer_notes")
    p.add_argument("--out", type=Path, help="report folder")
    p.add_argument("--ontology-dir", type=Path, help="cached / local ontology files (default ~/.cache/open-fdd/ontologies)")
    p.add_argument("--only", help="pinned sources to use, comma separated (brick,s223p,haystack)")
    p.add_argument("--ontology", type=Path, action="append", default=[], help="an extra local ontology file")
    p.add_argument("--refresh", action="store_true", help="download the pinned sources (sha256-checked) first")
    p.add_argument("--graph", type=Path, help="a building graph (Turtle, N-Triples, JSON-LD, RDF/XML): runs the doctor")
    p.add_argument("--from-nf", action="store_true", help="read the graph from an NF box's rdf hook (open-fdd[nf])")
    p.add_argument("--nf-url", help="NF URL (else NF_URL / NFURL / NF_LAN_URL)")
    p.add_argument("--env", help="KEY=VALUE env file for the NF client")
    p.add_argument("--app", choices=["full", "lite"], default="full")
    p.add_argument("--shacl", nargs="?", const="default", help="validate the graph with SHACL (default shapes or a file)")
    p.add_argument("--no-xlsx", action="store_true")
    p.add_argument("--example", action="store_true", help="use the shipped synthetic requirements and building graph")
    p.add_argument("--sources", action="store_true", help="print the pinned source manifest and exit")
    return p


def _parse_graph(path: Path):
    from open_fdd.ontology_audit.sources import parse_rdf

    return parse_rdf(path)


def run(args) -> int:
    from open_fdd.ontology_audit.sources import SOURCES

    if args.sources:
        print(json.dumps(SOURCES, indent=1))
        return 0
    if args.example:
        data = files("open_fdd.ontology_audit").joinpath("data")
        with as_file(data.joinpath("example_requirements.csv")) as req, as_file(data.joinpath("example_building.ttl")) as g:
            args.requirements = args.requirements or Path(req)
            args.graph = args.graph or Path(g)
            return _run(args)
    return _run(args)


def _run(args) -> int:
    from open_fdd.ontology_audit.audit import audit_requirements, summary
    from open_fdd.ontology_audit.doctor import doctor
    from open_fdd.ontology_audit.report import write_audit, write_doctor
    from open_fdd.ontology_audit.requirements import read_requirements
    from open_fdd.ontology_audit.sources import load_sources, refresh

    if args.requirements is None and args.graph is None and not args.from_nf:
        raise ValueError("give a requirements file, --graph, --from-nf or --example")
    if args.out is None:
        raise ValueError("--out is required")
    only = [s.strip() for s in args.only.split(",")] if args.only else None
    if args.refresh:
        refresh(args.ontology_dir, only, log=lambda m: print(m, file=sys.stderr))
    sources = load_sources(args.ontology_dir, only, args.ontology)
    for s in sources:
        print(f"source {s.name}: {s.status} {s.detail}", file=sys.stderr)
    graph = None
    if args.from_nf:
        from rdflib import Graph

        from open_fdd.ontology_audit.nf_adapter import fetch_turtle

        turtle, _ = fetch_turtle(url=args.nf_url, env_file=args.env, app=args.app)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "nf_model.ttl").write_text(turtle, encoding="utf-8")
        graph = Graph().parse(data=turtle, format="turtle")
    elif args.graph is not None:
        graph = _parse_graph(args.graph)
    if args.requirements is not None:
        rows = audit_requirements(read_requirements(args.requirements), sources, graph)
        paths = write_audit(rows, sources, args.out, xlsx=not args.no_xlsx)
        print(json.dumps({"audit": summary(rows), "files": {k: str(v) for k, v in paths.items()}}))
    if graph is not None:
        shacl = None
        if args.shacl:
            from open_fdd.ontology_audit.shacl import validate_shacl

            shapes = None if args.shacl == "default" else _parse_graph(Path(args.shacl))
            shacl = validate_shacl(graph, shapes)
        report = doctor(graph, sources)
        paths = write_doctor(report, args.out, shacl)
        print(json.dumps({"doctor": report.counts(), "problems": len(report.problems),
                          "files": {k: str(v) for k, v in paths.items()}}))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return run(args)
    except ImportError as exc:
        print(f'open-fdd-ontology-audit: missing dependency ({exc.name}): pip install "open-fdd[ontology]"',
              file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"open-fdd-ontology-audit: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
