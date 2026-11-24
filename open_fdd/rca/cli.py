"""``open-fdd-rca``: advisory graph-based HVAC root-cause analysis over RDF topology.

Examples::

    open-fdd-rca --example --print md
    open-fdd-rca --graph site.ttl --results rule_results.csv --out-dir rca_out
    open-fdd-rca --graph site.ttl --episodes confidence_out/episodes.jsonl --out-dir rca_out
    open-fdd-rca --from-nf --episodes confidence_out/episodes.jsonl --out-dir rca_out

Advisory only: reads topology and FDD/confidence outputs and writes ``rca_report.json``
and ``rca_report.md``. Never changes rules, tuners, tags, or setpoints.
"""

from __future__ import annotations

import argparse
import sys
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

from open_fdd.rca.evidence import (
    DataFrameEvidenceCollector,
    FaultEvidence,
    InMemoryEvidenceCollector,
    PointDeviation,
    parse_utc,
)
from open_fdd.rca.graph import load_graph, load_graph_from_nf
from open_fdd.rca.rank import analyze_rca
from open_fdd.rca.report import report_to_json, report_to_markdown

DESCRIPTION = (
    "Trace downstream HVAC fault symptoms upstream through Brick, ASHRAE 223P, and Haystack RDF "
    "relationships to rank likely root causes (JSON + Markdown). Advisory only."
)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="open-fdd-rca",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = ap.add_argument_group("topology source")
    src.add_argument("--graph", type=Path, help="Site RDF/Turtle model file (.ttl)")
    src.add_argument("--from-nf", action="store_true", help="Fetch Turtle model from a Normal Framework rdf hook")
    src.add_argument("--nf-url", help="NF URL (else NF_URL / NFURL / NF_LAN_URL)")
    src.add_argument("--env", help="KEY=VALUE env file for the NF client")
    src.add_argument("--app", choices=("full", "lite"), default="full")

    ev = ap.add_argument_group("fault & evidence input")
    ev.add_argument("--results", type=Path, help="CSV of Open-FDD rule_result or long-format fault flags")
    ev.add_argument("--episodes", type=Path, help="episodes.jsonl, episodes.csv, or report.json from open-fdd-ml confidence")
    ev.add_argument("--deviations", type=Path, help="Optional CSV of SI point deviations (equipment_id, role, value_si, setpoint_si, unit)")
    ev.add_argument("--dq", type=Path, help="Optional CSV of data-quality warnings (equipment_id, flag, point_id, detail)")
    ev.add_argument("--example", action="store_true", help="Run on the shipped synthetic plant fixture and sample faults")

    flt = ap.add_argument_group("filtering & output")
    flt.add_argument("--symptom-equip", help="Focus on one downstream symptom equipment id or label")
    flt.add_argument("--symptom-rule", help="Focus on one symptom rule id")
    flt.add_argument("--site", help="Scope topology and faults to one site id")
    flt.add_argument("--top", type=int, default=5, help="Top candidate causes per symptom (default 5)")
    flt.add_argument("--out-dir", type=Path, default=None, help="Directory to write rca_report.json and rca_report.md")
    flt.add_argument("--print", dest="print_format", choices=("json", "md", "none"), default="json")
    return ap


def _read_csv_dicts(path: Path) -> list[dict[str, Any]]:
    import csv

    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _example_collector() -> InMemoryEvidenceCollector:
    faults = [
        FaultEvidence(
            equipment_id="ahu-1",
            rule_id="SAT-HIGH",
            start=parse_utc("2026-11-24T10:00:00Z"),
            end=parse_utc("2026-11-24T12:00:00Z"),
            p_real=0.92,
            p_false_positive=0.04,
            confidence_label="likely_real",
        ),
        FaultEvidence(
            equipment_id="vav-1",
            rule_id="AIRFLOW-LOW",
            start=parse_utc("2026-11-24T10:10:00Z"),
            end=parse_utc("2026-11-24T12:00:00Z"),
            p_real=0.10,
            p_false_positive=0.86,
            confidence_label="likely_false_positive",
        ),
        FaultEvidence(
            equipment_id="zone-1",
            rule_id="ZNT-HIGH",
            start=parse_utc("2026-11-24T10:15:00Z"),
            end=parse_utc("2026-11-24T12:00:00Z"),
            p_real=0.88,
            p_false_positive=0.06,
            confidence_label="likely_real",
        ),
        FaultEvidence(
            equipment_id="zone-2",
            rule_id="ZNT-HIGH",
            start=parse_utc("2026-11-24T10:20:00Z"),
            end=parse_utc("2026-11-24T12:00:00Z"),
            p_real=0.85,
            p_false_positive=0.08,
            confidence_label="likely_real",
        ),
        FaultEvidence(
            equipment_id="zone-unlinked",
            rule_id="ZNT-HIGH",
            start=parse_utc("2026-11-24T10:25:00Z"),
            end=parse_utc("2026-11-24T12:00:00Z"),
            p_real=0.80,
            p_false_positive=0.10,
            confidence_label="likely_real",
        ),
    ]
    devs = [
        PointDeviation(
            equipment_id="ahu-1",
            role="discharge-air-temp",
            value_si=18.5,
            setpoint_si=13.0,
            unit="degC",
            timestamp=parse_utc("2026-11-24T10:30:00Z"),
        )
    ]
    return InMemoryEvidenceCollector(faults=faults, point_deviations=devs)


def run(args: argparse.Namespace) -> int:
    if args.example:
        data = files("open_fdd.rca").joinpath("data")
        with as_file(data.joinpath("example_plant.ttl")) as ttl_path:
            graph = load_graph(Path(ttl_path))
        collector = _example_collector()
        source_meta: dict[str, Any] = {"mode": "example"}
    else:
        if args.from_nf:
            # TODO(5.0.22): also allow fetching fdd.rule_result / point deviations directly via NF client/hook.
            graph = load_graph_from_nf(url=args.nf_url, env_file=args.env, app=args.app)
            source_meta = {"topology": "nf_rdf_hook", "app": args.app}
        elif args.graph is not None:
            graph = load_graph(args.graph)
            source_meta = {"topology": str(args.graph)}
        else:
            raise ValueError("Provide --graph, --from-nf, or --example")

        devs = _read_csv_dicts(args.deviations) if args.deviations else None
        dq = _read_csv_dicts(args.dq) if args.dq else None
        if args.episodes is not None:
            collector = DataFrameEvidenceCollector.from_confidence_episodes(args.episodes, deviations=devs, data_quality=dq)
            source_meta["evidence"] = str(args.episodes)
        elif args.results is not None:
            collector = DataFrameEvidenceCollector.from_rule_results(_read_csv_dicts(args.results), deviations=devs, data_quality=dq)
            source_meta["evidence"] = str(args.results)
        else:
            raise ValueError("Provide --results, --episodes, or --example")

    report = analyze_rca(
        graph,
        collector,
        symptom_equip=args.symptom_equip,
        symptom_rule=args.symptom_rule,
        site_id=args.site,
        top=args.top,
    )
    json_text = report_to_json(report, source=source_meta)
    md_text = report_to_markdown(report)

    if args.out_dir is not None:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "rca_report.json").write_text(json_text + "\n", encoding="utf-8")
        (args.out_dir / "rca_report.md").write_text(md_text, encoding="utf-8")

    if args.print_format == "json":
        print(json_text)
    elif args.print_format == "md":
        print(md_text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())